"""Integração de consumo das métricas agregadas publicadas pelo componente S5."""

from src.modulo_s5.metrics_store import S5MetricsStore
from src.modulo_s5.kafka_consumer import S5MetricsKafkaConsumer, validar_envelope_s5

__all__ = ["S5MetricsStore", "S5MetricsKafkaConsumer", "validar_envelope_s5"]
