#!/usr/bin/env python3
import argparse
import datetime
import json
import uuid

try:
    from confluent_kafka import Producer
except ImportError:
    Producer = None


def envelope(event_type, count, uncertain_count, duration_avg_ms, start):
    end = start + datetime.timedelta(hours=1)
    return {
        "message_id": str(uuid.uuid4()),
        "message_type": "event",
        "schema": "ods.s5.event.metrics",
        "schema_version": "1.0",
        "producer": "S5",
        "occurred_at": start.isoformat(),
        "payload": {
            "event_type": event_type,
            "zone_id": "restaurant-main",
            "window_start_at": start.isoformat(),
            "window_end_at": end.isoformat(),
            "granularity": "HOUR",
            "count": count,
            "uncertain_count": uncertain_count,
            "duration_avg_ms": duration_avg_ms,
            "demo": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Publica métricas mockadas do S5 diretamente no Kafka.")
    parser.add_argument("--bootstrap", default="34.66.235.91:9093")
    parser.add_argument("--topic", default="ods.s5.event.metrics")
    parser.add_argument("--days", type=int, default=7, help="Quantidade de dias históricos fictícios")
    args = parser.parse_args()

    if Producer is None:
        raise SystemExit("Instale 'confluent-kafka' para publicar os dados mockados: pip install confluent-kafka")

    producer = Producer({"bootstrap.servers": args.bootstrap})
    delivered = []

    def delivery_report(error, message):
        if error is not None:
            print(f"[ERRO Kafka S5] {error}")
        else:
            delivered.append(message.value())
            print(f"[Kafka S5 -> A7] Entregue em {message.topic()} [{message.partition()}]")

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_profiles = [58, 72, 64, 89, 104, 118, 96]
    hours = (11, 12, 13, 18, 19, 20, 21)
    payloads = []

    for day_offset in range(max(1, args.days)):
        day = today - datetime.timedelta(days=max(1, args.days) - 1 - day_offset)
        profile = day_profiles[(day.weekday()) % len(day_profiles)]
        for hour_index, hour in enumerate(hours):
            weight = (18, 24, 20, 27, 30, 23, 16)[hour_index]
            count = max(2, round(profile * weight / 100))
            uncertain_count = round(count * (0.05 + (hour_index % 3) * 0.025))
            duration_avg_ms = (660000 + hour_index * 42000 + (day.weekday() % 3) * 30000)
            payloads.append(
                envelope(
                    "DEMO_METRIC_TYPE",
                    count,
                    uncertain_count,
                    duration_avg_ms,
                    day.replace(hour=hour),
                )
            )
    for payload in payloads:
        producer.produce(
            args.topic,
            key=payload["payload"]["event_type"].encode("utf-8"),
            value=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            callback=delivery_report,
        )
    producer.flush(10)


if __name__ == "__main__":
    main()
