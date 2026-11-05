"""
Módulo Consumidor do Barramento Kafka para o Componente A7 (Varejo).

Consome em tempo real os eventos de transcrição publicados pelo Componente I5
no tópico `ods.i5.transcript` (Integração B2), validando o envelope canônico B1/B2
em 3 níveis, garantindo idempotência por `message_id` (RNF06) e respeitando a
flag booleana `uncertain` (RF07).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Tuple, Union

try:
    from confluent_kafka import Consumer as ConfluentConsumer, KafkaError
except ImportError:
    ConfluentConsumer = None
    KafkaError = None

try:
    import yaml
except ImportError:
    yaml = None

from src.modulo_jornada.jornada import SessionManager
from src.modulo_nlu.subscriber import AudioEventSubscriber

logger = logging.getLogger("A7.KafkaConsumer")

DEFAULT_BOOTSTRAP_SERVERS = "34.66.235.91:9093"
DEFAULT_TOPIC = "ods.i5.transcript"
DEFAULT_GROUP_ID = "a7-varejo-nlu"
PRODUCER_ESPERADO = "I5"
SCHEMAS_ACEITOS: Set[str] = {"ods.i5.transcript", "ods.varejo.transcricao"}
VERSAO_SUPORTADA_PREFIXO = "1."

CAMPOS_OBRIGATORIOS_ENVELOPE = [
    "message_id",
    "message_type",
    "schema",
    "schema_version",
    "producer",
    "occurred_at",
    "payload",
]


def validar_envelope_i5(
    evento: Any,
    schemas_aceitos: Optional[Set[str]] = None,
    versao_suportada_prefixo: str = VERSAO_SUPORTADA_PREFIXO,
) -> Tuple[bool, Optional[str]]:
    """
    Valida o envelope B1/B2 recebido do I5 em três níveis conforme a Seção 4.3 do Guia B2:
    1) Campos obrigatórios do envelope;
    2) Tipo de evento (`message_type == "event"`), `producer == "I5"`, `schema` e `schema_version`;
    3) Estrutura do `payload` (flag booleana `uncertain` ou `duvida_explicita`, texto e confiança em [0, 1]).
    """
    if not isinstance(evento, dict):
        return False, "evento não é um dicionário JSON"

    # Nível 1: Campos obrigatórios do envelope
    for campo in CAMPOS_OBRIGATORIOS_ENVELOPE:
        if campo not in evento:
            return False, f"campo obrigatório ausente no envelope: {campo}"

    if not str(evento.get("message_id", "")).strip():
        return False, "message_id vazio"

    # Nível 2: Metadados do contrato B1/B2
    if evento.get("message_type") != "event":
        return False, f"message_type inválido: {evento.get('message_type')}"

    if evento.get("producer") != PRODUCER_ESPERADO:
        return False, f"producer inesperado: {evento.get('producer')} (esperado: {PRODUCER_ESPERADO})"

    aceitos = schemas_aceitos or SCHEMAS_ACEITOS
    schema_recebido = str(evento.get("schema", ""))
    if schema_recebido not in aceitos:
        return False, f"schema inesperado: {schema_recebido} (aceitos: {sorted(aceitos)})"

    versao = str(evento.get("schema_version", ""))
    if not versao.startswith(versao_suportada_prefixo):
        return False, f"versão do schema não suportada: {versao}"

    # Nível 3: Validação do payload do I5
    payload = evento.get("payload")
    if not isinstance(payload, dict):
        return False, "payload não é um objeto JSON"

    if "uncertain" in payload and not isinstance(payload["uncertain"], bool):
        return False, "campo 'uncertain' no payload deve ser booleano"

    if "uncertain" not in payload and "duvida_explicita" not in payload:
        return False, "payload sem a flag booleana obrigatória 'uncertain'"

    conf = payload.get("confianca_geral", payload.get("confidence", payload.get("confianca")))
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0.0 <= float(conf) <= 1.0):
        return False, "confianca_geral/confidence ausente ou fora do intervalo [0.0, 1.0]"

    if "texto_transcrito" not in payload and "texto" not in payload:
        return False, "payload sem campo 'texto_transcrito' ou 'texto'"

    return True, None


class TranscriptKafkaConsumer:
    """
    Consumidor Kafka do Componente A7 que escuta `ods.i5.transcript`, valida o
    contrato B1/B2 e aciona o pipeline NLU (`AudioEventSubscriber`) + Jornada (`SessionManager`).
    """

    def __init__(
        self,
        subscriber: AudioEventSubscriber,
        session_manager: SessionManager,
        bootstrap_servers: Optional[str] = None,
        topic: Optional[str] = None,
        group_id: Optional[str] = None,
        auto_offset_reset: str = "latest",
        poll_timeout_s: float = 1.0,
        enable_auto_commit: bool = True,
        consumer_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
        extra_kafka_config: Optional[Dict[str, Any]] = None,
    ):
        self.subscriber = subscriber
        self.session_manager = session_manager
        self.bootstrap_servers = (
            bootstrap_servers
            or os.getenv("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_BOOTSTRAP_SERVERS)
        ).strip()
        self.topic = (
            topic
            or os.getenv("KAFKA_TOPIC", DEFAULT_TOPIC)
        ).strip()
        self.group_id = (
            group_id
            or os.getenv("KAFKA_GROUP_ID", DEFAULT_GROUP_ID)
        ).strip()
        self.auto_offset_reset = auto_offset_reset
        self.poll_timeout_s = float(poll_timeout_s)
        self.enable_auto_commit = bool(enable_auto_commit)

        self.running = False
        self._bg_thread: Optional[threading.Thread] = None

        kafka_config: Dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "reconnect.backoff.ms": 1000,
            "reconnect.backoff.max.ms": 10000,
        }
        if extra_kafka_config:
            kafka_config.update(extra_kafka_config)
        self.kafka_config = kafka_config

        factory = consumer_factory or ConfluentConsumer
        if factory is None:
            raise RuntimeError(
                "A biblioteca 'confluent-kafka' não está instalada. "
                "Instale com: pip install confluent-kafka"
            )
        self._consumer = factory(self.kafka_config)
        self._consumer.subscribe([self.topic])

    @classmethod
    def from_config(
        cls,
        subscriber: AudioEventSubscriber,
        session_manager: SessionManager,
        config_path: Union[str, Path] = "config/slm_config.yaml",
        bootstrap_servers: Optional[str] = None,
        topic: Optional[str] = None,
        group_id: Optional[str] = None,
        auto_offset_reset: Optional[str] = None,
        consumer_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> "TranscriptKafkaConsumer":
        """Instancia o consumidor carregando os parâmetros da seção `kafka` do YAML."""
        kafka_cfg: Dict[str, Any] = {}
        path_obj = Path(config_path)
        if not path_obj.exists():
            alt = Path(__file__).resolve().parents[2] / config_path
            if alt.exists():
                path_obj = alt

        if path_obj.exists() and yaml is not None:
            try:
                with open(path_obj, "r", encoding="utf-8") as f:
                    dados = yaml.safe_load(f)
                    if isinstance(dados, dict) and isinstance(dados.get("kafka"), dict):
                        kafka_cfg = dados["kafka"]
            except Exception as e:
                logger.warning("Falha ao ler configuração Kafka de %s: %s", path_obj, e)

        return cls(
            subscriber=subscriber,
            session_manager=session_manager,
            bootstrap_servers=bootstrap_servers or kafka_cfg.get("bootstrap_servers"),
            topic=topic or kafka_cfg.get("topic_input"),
            group_id=group_id or kafka_cfg.get("group_id"),
            auto_offset_reset=str(auto_offset_reset or kafka_cfg.get("auto_offset_reset", "latest")),
            poll_timeout_s=float(kafka_cfg.get("poll_timeout_s", 1.0)),
            enable_auto_commit=bool(kafka_cfg.get("enable_auto_commit", True)),
            consumer_factory=consumer_factory,
        )

    def process_raw_message(
        self, raw_bytes: Union[bytes, str]
    ) -> Optional[Dict[str, Any]]:
        """
        Desserializa uma mensagem crua do Kafka, valida o envelope B1/B2 em 3 níveis
        e despacha para o NLU e para o SessionManager.
        """
        try:
            texto_json = (
                raw_bytes.decode("utf-8")
                if isinstance(raw_bytes, bytes)
                else str(raw_bytes)
            )
            evento = json.loads(texto_json)
        except Exception as e:
            logger.warning("[A7 - Kafka] Mensagem descartada (JSON inválido): %s", e)
            return None

        schemas_validos = set(SCHEMAS_ACEITOS) | {self.topic}
        valido, motivo = validar_envelope_i5(evento, schemas_aceitos=schemas_validos)
        if not valido:
            logger.warning("[A7 - Kafka] Envelope inválido descartado: %s", motivo)
            return None

        nlu_out = self.subscriber.on_message_received(evento)
        jornada_out = self.session_manager.handle_nlu_result(nlu_out)

        return {
            "envelope": evento,
            "nlu": nlu_out,
            "jornada": jornada_out,
        }

    def listen_forever(
        self,
        max_messages: Optional[int] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> int:
        """
        Loop principal de escuta contínua do tópico Kafka.
        Retorna a quantidade de mensagens válidas processadas.
        """
        self.running = True
        processadas = 0
        logger.info(
            "[A7 - Kafka] Escutando tópico '%s' em '%s' (group.id=%s)...",
            self.topic,
            self.bootstrap_servers,
            self.group_id,
        )

        try:
            while self.running:
                msg = self._consumer.poll(self.poll_timeout_s)
                if msg is None:
                    continue

                err = msg.error() if hasattr(msg, "error") else None
                if err is not None:
                    # Ignora erros transitórios comuns durante rebalanceamento e descoberta
                    err_code = err.code() if hasattr(err, "code") else None
                    if err_code in (
                        3,    # UNKNOWN_TOPIC_OR_PART
                        -191, # _PARTITION_EOF
                        -168, # _NO_OFFSET
                    ):
                        continue
                    if KafkaError is not None and hasattr(err, "code"):
                        if err.code() in (
                            KafkaError._PARTITION_EOF,
                            KafkaError._UNKNOWN_TOPIC_OR_PART,
                            getattr(KafkaError, "_NO_OFFSET", -168),
                        ):
                            continue
                    logger.error("[A7 - Kafka] Erro ao consumir mensagem: %s", err)
                    continue

                resultado = self.process_raw_message(msg.value())
                if resultado is not None:
                    processadas += 1
                    if on_event is not None:
                        on_event(resultado)

                if max_messages is not None and processadas >= max_messages:
                    break
        except KeyboardInterrupt:
            logger.info("[A7 - Kafka] Interrupção recebida pelo usuário.")
        finally:
            self.close()

        return processadas

    def start_background(
        self, on_event: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> threading.Thread:
        """Inicia o consumidor em uma thread daemon em background (ideal para o FastAPI)."""
        if self._bg_thread and self._bg_thread.is_alive():
            return self._bg_thread

        self.running = True
        self._bg_thread = threading.Thread(
            target=self.listen_forever,
            kwargs={"on_event": on_event},
            daemon=True,
            name="A7KafkaConsumerWorker",
        )
        self._bg_thread.start()
        return self._bg_thread

    def close(self) -> None:
        """Encerra o loop de leitura e fecha a conexão com o broker Kafka."""
        self.running = False
        try:
            self._consumer.close()
        except Exception as e:
            logger.warning("[A7 - Kafka] Aviso ao fechar consumidor: %s", e)

