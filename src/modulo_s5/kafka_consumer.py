from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple, Union

try:
    from confluent_kafka import Consumer as ConfluentConsumer
except ImportError:
    ConfluentConsumer = None

from src.modulo_s5.metrics_store import S5MetricsStore

logger = logging.getLogger("A7.S5KafkaConsumer")


def validar_envelope_s5(evento: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(evento, dict):
        return False, "evento não é um dicionário JSON"

    required = [
        "message_id",
        "message_type",
        "schema",
        "schema_version",
        "producer",
        "occurred_at",
        "payload",
    ]
    for field in required:
        if field not in evento:
            return False, f"campo obrigatório ausente no envelope: {field}"
    if not str(evento.get("message_id", "")).strip():
        return False, "message_id vazio"
    if evento.get("message_type") != "event":
        return False, "message_type inválido: esperado event"
    if evento.get("producer") != "S5":
        return False, "producer inválido: esperado S5"
    if evento.get("schema") != "ods.s5.event.metrics":
        return False, "schema inválido: esperado ods.s5.event.metrics"
    if not str(evento.get("schema_version", "")).startswith("1."):
        return False, "schema_version incompatível: esperado versão 1.x"

    payload = evento.get("payload")
    if not isinstance(payload, dict):
        return False, "payload não é um objeto JSON"

    required_payload = [
        "event_type",
        "zone_id",
        "window_start_at",
        "window_end_at",
        "granularity",
        "count",
    ]
    for field in required_payload:
        if field not in payload:
            return False, f"campo obrigatório ausente no payload S5: {field}"

    count = payload["count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return False, "count deve ser um inteiro maior ou igual a zero"
    for field in ("uncertain_count", "duration_avg_ms"):
        if field in payload:
            value = payload[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False, f"{field} deve ser um inteiro maior ou igual a zero"
    uncertain_count = payload.get("uncertain_count")
    if uncertain_count is not None and uncertain_count > count:
        return False, "uncertain_count não pode ser maior que count"
    return True, None


class S5MetricsKafkaConsumer:
    """Consumidor das métricas agregadas publicadas pelo S5."""

    def __init__(
        self,
        metrics_store: S5MetricsStore,
        bootstrap_servers: str = "34.66.235.91:9093",
        topic: str = "ods.s5.event.metrics",
        group_id: str = "a7-admin-s5",
        consumer_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        if consumer_factory is None and ConfluentConsumer is None:
            raise RuntimeError("A biblioteca 'confluent-kafka' não está instalada.")
        self.metrics_store = metrics_store
        self.bootstrap_servers = bootstrap_servers.strip()
        self.topic = topic.strip()
        self.group_id = group_id.strip()
        self.running = False
        self._bg_thread: Optional[threading.Thread] = None
        factory = consumer_factory or ConfluentConsumer
        self._consumer = factory(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": self.group_id,
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        self._consumer.subscribe([self.topic])

    def process_raw_message(self, raw_bytes: Union[bytes, str]) -> Optional[Dict[str, Any]]:
        try:
            text = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else str(raw_bytes)
            envelope = json.loads(text)
        except Exception as exc:
            logger.warning("[A7 - S5] Mensagem JSON inválida descartada: %s", exc)
            return None
        valid, reason = validar_envelope_s5(envelope)
        if not valid:
            logger.warning("[A7 - S5] Envelope inválido descartado: %s", reason)
            return None
        envelope["transport"] = "kafka"
        if not self.metrics_store.ingest(envelope):
            return None
        return envelope

    def listen_forever(self, max_messages: Optional[int] = None) -> int:
        self.running = True
        processed = 0
        try:
            while self.running:
                message = self._consumer.poll(1.0)
                if message is None:
                    continue
                if hasattr(message, "error") and message.error() is not None:
                    continue
                if self.process_raw_message(message.value()) is not None:
                    processed += 1
                if max_messages is not None and processed >= max_messages:
                    break
        finally:
            self.close()
        return processed

    def start_background(self) -> threading.Thread:
        if self._bg_thread and self._bg_thread.is_alive():
            return self._bg_thread
        self.running = True
        self._bg_thread = threading.Thread(
            target=self.listen_forever,
            daemon=True,
            name="A7S5MetricsConsumerWorker",
        )
        self._bg_thread.start()
        return self._bg_thread

    def close(self) -> None:
        self.running = False
        try:
            self._consumer.close()
        except Exception as exc:
            logger.warning("[A7 - S5] Aviso ao fechar consumidor: %s", exc)
