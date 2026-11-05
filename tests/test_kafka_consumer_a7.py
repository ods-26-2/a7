"""
Testes unitários e de integração para o Consumidor Kafka (B2) do Componente A7.
Valida:
1. Contrato do envelope B1/B2 em 3 níveis (ods.i5.transcript).
2. Integração fim-a-fim (Consumer -> AudioEventSubscriber -> Classifier -> SessionManager).
3. Regra RF07: Dúvida explícita / flag booleana `uncertain=True` bloqueando mutação silenciosa.
4. Regra RNF06: Idempotência por `message_id` evitando duplicação de itens em retransmissões Kafka.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_jornada.jornada import SessionManager, SessionState
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.kafka_consumer import (
    DEFAULT_BOOTSTRAP_SERVERS,
    DEFAULT_GROUP_ID,
    DEFAULT_TOPIC,
    TranscriptKafkaConsumer,
    validar_envelope_i5,
)
from src.modulo_nlu.subscriber import AudioEventSubscriber
from src.modulo_s5.kafka_consumer import S5MetricsKafkaConsumer, validar_envelope_s5
from src.modulo_s5.metrics_store import S5MetricsStore


def _criar_envelope_i5_valido(
    texto: str = "quero dois x-saladas",
    confianca: float = 0.94,
    uncertain: bool = False,
    origem: str = "mic_mesa_01",
    message_id: Optional[str] = None,
    schema: str = DEFAULT_TOPIC,
) -> Dict[str, Any]:
    return {
        "message_id": message_id or str(uuid.uuid4()),
        "message_type": "event",
        "schema": schema,
        "schema_version": "1.0",
        "producer": "I5",
        "artifact_version": "whisper-small-trt-fp16:1.0.0",
        "occurred_at": "2026-11-05T00:00:00Z",
        "published_at": "2026-11-05T00:00:00Z",
        "payload": {
            "origem": origem,
            "timestamp_inicio": "2026-11-05T00:00:00Z",
            "timestamp_fim": "2026-11-05T00:00:02Z",
            "texto_transcrito": texto,
            "texto_preprocessado": texto.lower(),
            "confianca_geral": confianca,
            "confidence": confianca,
            "uncertain": uncertain,
            "duvida_explicita": uncertain,
        },
    }


class FakeKafkaMessage:
    def __init__(self, value_bytes: bytes, err: Any = None):
        self._value = value_bytes
        self._err = err

    def value(self) -> bytes:
        return self._value

    def error(self) -> Any:
        return self._err


class FakeKafkaConsumerClient:
    def __init__(self, messages: List[FakeKafkaMessage]):
        self.messages = list(messages)
        self.subscribed_topics: List[str] = []
        self.closed = False

    def subscribe(self, topics: List[str]) -> None:
        self.subscribed_topics = list(topics)

    def poll(self, timeout: float = 1.0) -> Optional[FakeKafkaMessage]:
        if self.messages:
            return self.messages.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


def test_validacao_envelope_i5_tres_niveis():
    """Garante que a validação em 3 níveis aceita envelopes B1/B2 legítimos e rejeita malformados."""
    env_ok = _criar_envelope_i5_valido()
    valido, motivo = validar_envelope_i5(env_ok)
    assert valido is True
    assert motivo is None

    # Nível 1: Falta campo obrigatório
    env_sem_id = dict(env_ok)
    env_sem_id.pop("message_id")
    valido, motivo = validar_envelope_i5(env_sem_id)
    assert valido is False
    assert "message_id" in str(motivo)

    # Nível 2: Producer incorreto
    env_prod_errado = dict(env_ok, producer="P5")
    valido, motivo = validar_envelope_i5(env_prod_errado)
    assert valido is False
    assert "producer" in str(motivo)

    # Nível 3: Flag booleana uncertain ausente ou inválida
    env_sem_uncertain = _criar_envelope_i5_valido()
    env_sem_uncertain["payload"].pop("uncertain")
    env_sem_uncertain["payload"].pop("duvida_explicita")
    valido, motivo = validar_envelope_i5(env_sem_uncertain)
    assert valido is False
    assert "uncertain" in str(motivo)

    # Nível 3: Confiança fora de [0.0, 1.0]
    env_conf_invalida = _criar_envelope_i5_valido(confianca=1.5)
    valido, motivo = validar_envelope_i5(env_conf_invalida)
    assert valido is False
    assert "confianca" in str(motivo)


def test_consumo_kafka_fim_a_fim_adiciona_item_ao_carrinho():
    """Simula o recebimento de um evento real do I5 via Kafka adicionando itens à sessão."""
    catalogo = CatalogoRepository("data/cardapio_mock.json")
    subscriber = AudioEventSubscriber(IntentClassifier(catalogo))
    manager = SessionManager(catalogo_repo=catalogo)

    env = _criar_envelope_i5_valido(
        texto="quero dois x-salada",
        confianca=0.95,
        uncertain=False,
        origem="mic_mesa_01",
    )
    msg_bytes = json.dumps(env).encode("utf-8")
    fake_client = FakeKafkaConsumerClient([FakeKafkaMessage(msg_bytes)])

    consumer = TranscriptKafkaConsumer.from_config(
        subscriber=subscriber,
        session_manager=manager,
        config_path="config/slm_config.yaml",
        consumer_factory=lambda _cfg: fake_client,
    )

    assert consumer.bootstrap_servers == DEFAULT_BOOTSTRAP_SERVERS
    assert consumer.topic == DEFAULT_TOPIC
    assert consumer.group_id == DEFAULT_GROUP_ID
    assert fake_client.subscribed_topics == [DEFAULT_TOPIC]

    eventos_recebidos = []
    qtd = consumer.listen_forever(max_messages=1, on_event=eventos_recebidos.append)

    assert qtd == 1
    assert len(eventos_recebidos) == 1
    assert fake_client.closed is True

    sessao = manager.obter_sessao("mic_mesa_01")
    assert sessao is not None
    assert sessao.state == SessionState.ACTIVE
    assert len(sessao.cart.itens) == 1
    assert sessao.cart.itens[0].nome == "X-Salada"
    assert sessao.cart.itens[0].quantidade == 2


def test_regra_rf07_flag_uncertain_bloqueia_mutacao_silenciosa():
    """
    Mesmo com confiança numérica >= 0.5 (ex: ruído excessivo detectado pelo I5),
    se `uncertain=True`, o A7 deve marcar como INDETERMINADO e colocar a sessão em PENDING.
    """
    catalogo = CatalogoRepository("data/cardapio_mock.json")
    subscriber = AudioEventSubscriber(IntentClassifier(catalogo))
    manager = SessionManager(catalogo_repo=catalogo)

    env_incerto = _criar_envelope_i5_valido(
        texto="quero um x-bacon",
        confianca=0.82,
        uncertain=True,
        origem="mic_balcao_02",
    )
    fake_client = FakeKafkaConsumerClient([FakeKafkaMessage(json.dumps(env_incerto).encode("utf-8"))])

    consumer = TranscriptKafkaConsumer(
        subscriber=subscriber,
        session_manager=manager,
        consumer_factory=lambda _cfg: fake_client,
    )

    resultado = consumer.process_raw_message(json.dumps(env_incerto).encode("utf-8"))
    assert resultado is not None
    assert resultado["nlu"]["intencao"] == "INDETERMINADO"
    assert resultado["nlu"]["uncertain"] is True

    sessao = manager.obter_sessao("mic_balcao_02")
    assert sessao is not None
    assert sessao.state == SessionState.PENDING
    assert len(sessao.cart.itens) == 0


def test_regra_rnf06_idempotencia_por_message_id():
    """
    Garante que o reenvio do mesmo evento Kafka (mesmo message_id) em retransmissões
    de rede não duplica os itens no carrinho da sessão.
    """
    catalogo = CatalogoRepository("data/cardapio_mock.json")
    subscriber = AudioEventSubscriber(IntentClassifier(catalogo))
    manager = SessionManager(catalogo_repo=catalogo)

    msg_id_fixo = str(uuid.uuid4())
    env = _criar_envelope_i5_valido(
        texto="quero um x-bacon",
        confianca=0.96,
        uncertain=False,
        origem="mic_totem_01",
        message_id=msg_id_fixo,
    )
    raw = json.dumps(env).encode("utf-8")

    fake_client = FakeKafkaConsumerClient([FakeKafkaMessage(raw), FakeKafkaMessage(raw)])
    consumer = TranscriptKafkaConsumer(
        subscriber=subscriber,
        session_manager=manager,
        consumer_factory=lambda _cfg: fake_client,
    )

    # Primeira entrega: adiciona 1x X-Bacon
    res1 = consumer.process_raw_message(raw)
    assert res1 is not None
    assert res1["jornada"].get("duplicado") is not True

    # Segunda entrega (retransmissão com mesmo message_id): deve ser ignorada
    res2 = consumer.process_raw_message(raw)
    assert res2 is not None
    assert res2["jornada"].get("duplicado") is True

    sessao = manager.obter_sessao("mic_totem_01")
    assert sessao is not None
    assert len(sessao.cart.itens) == 1
    assert sessao.cart.itens[0].quantidade == 1


def test_consumo_kafka_metricas_s5_sem_dados_embutidos_na_api():
    store = S5MetricsStore()
    assert store.snapshot()["source"] == "s5-aguardando"
    assert store.snapshot()["summary"]["metric_events"] == 0

    envelope = {
        "message_id": str(uuid.uuid4()),
        "message_type": "event",
        "schema": "ods.s5.event.metrics",
        "schema_version": "1.0",
        "producer": "S5",
        "occurred_at": "2026-11-05T12:30:00Z",
        "payload": {
            "event_type": "MOCK_METRIC_TYPE",
            "zone_id": "restaurant-main",
            "window_start_at": "2026-11-05T12:00:00Z",
            "window_end_at": "2026-11-05T13:00:00Z",
            "granularity": "HOUR",
            "count": 9,
            "uncertain_count": 1,
            "duration_avg_ms": 846000,
        },
    }
    raw = json.dumps(envelope).encode("utf-8")
    valid, reason = validar_envelope_s5(envelope)
    assert valid is True, reason

    fake_client = FakeKafkaConsumerClient([FakeKafkaMessage(raw), FakeKafkaMessage(raw)])
    consumer = S5MetricsKafkaConsumer(
        metrics_store=store,
        consumer_factory=lambda _cfg: fake_client,
    )
    assert fake_client.subscribed_topics == ["ods.s5.event.metrics"]
    assert consumer.listen_forever(max_messages=1) == 1

    snapshot = store.snapshot()
    assert snapshot["source"] == "s5-kafka"
    assert snapshot["summary"]["total_count"] == 9
    assert snapshot["summary"]["duration_avg_minutes"] == 14.1


def test_snapshot_s5_calcula_historico_diario_semanal_e_picos():
    store = S5MetricsStore()

    for date_value, count in (
        ("2026-11-02", 20),
        ("2026-11-03", 40),
        ("2026-11-04", 30),
        ("2026-11-05", 60),
    ):
        envelope = {
            "message_id": str(uuid.uuid4()),
            "message_type": "event",
            "schema": "ods.s5.event.metrics",
            "schema_version": "1.0",
            "producer": "S5",
            "occurred_at": f"{date_value}T12:30:00Z",
            "payload": {
                "event_type": "DEMO_METRIC_TYPE",
                "zone_id": "restaurant-main",
                "window_start_at": f"{date_value}T12:00:00Z",
                "window_end_at": f"{date_value}T13:00:00Z",
                "granularity": "HOUR",
                "count": count,
                "uncertain_count": 2,
                "duration_avg_ms": 600000,
                "demo": True,
            },
        }
        assert store.ingest(envelope) is True

    snapshot = store.snapshot()
    assert snapshot["demonstration"] is True
    assert snapshot["insights"]["peak_hour"]["hour"] == "12:00"
    assert snapshot["insights"]["peak_day"]["date"] == "2026-11-05"
    assert snapshot["insights"]["peak_day"]["count"] == 60
    assert snapshot["insights"]["average_daily_count"] == 37.5
    assert snapshot["insights"]["busiest_weekday"]["weekday"] == "Quinta-feira"
