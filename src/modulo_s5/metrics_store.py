from __future__ import annotations

import threading
from typing import Any, Dict, List, Set


class S5MetricsStore:
    """Mantém em memória o último conjunto de métricas recebido do S5."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processed_message_ids: Set[str] = set()
        self.events: List[Dict[str, Any]] = []
        self.source = "s5-aguardando"

    def ingest(self, envelope: Dict[str, Any]) -> bool:
        message_id = str(envelope.get("message_id", "")).strip()
        if not message_id:
            return False
        with self._lock:
            if message_id in self._processed_message_ids:
                return False
            self._processed_message_ids.add(message_id)
            self.events.append(envelope)
            self.source = "s5-kafka" if envelope.get("transport") == "kafka" else "s5-desconhecido"
        return True

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self.events]

        by_event: Dict[str, Dict[str, Any]] = {}
        hourly: Dict[str, Dict[str, Any]] = {}
        zones: Dict[str, int] = {}
        daily: Dict[str, Dict[str, Any]] = {}
        weekdays: Dict[str, Dict[str, Any]] = {}
        demonstration = False

        uncertain = 0
        total_count = 0
        duration_total = 0
        duration_weight = 0

        for envelope in events:
            payload = envelope.get("payload", {})
            if not isinstance(payload, dict):
                continue

            event_type = str(payload.get("event_type", "UNKNOWN"))
            count = int(payload.get("count", 0) or 0)
            uncertain_count = int(payload.get("uncertain_count", 0) or 0)
            duration = int(payload.get("duration_avg_ms", 0) or 0)
            zone_id = str(payload.get("zone_id", "UNKNOWN"))
            if payload.get("demo") is True or event_type.startswith("DEMO_") or event_type.startswith("MOCK_"):
                demonstration = True

            total_count += count
            uncertain += uncertain_count
            zones[zone_id] = zones.get(zone_id, 0) + count

            event_summary = by_event.setdefault(
                event_type,
                {"count": 0, "uncertain_count": 0},
            )
            event_summary["count"] += count
            event_summary["uncertain_count"] += uncertain_count

            if duration and count:
                duration_total += duration * count
                duration_weight += count

            start = str(payload.get("window_start_at", ""))
            hour_key = start[11:16] if len(start) >= 16 else "Sem janela"
            hour_summary = hourly.setdefault(
                hour_key,
                {
                    "hour": hour_key,
                    "count": 0,
                    "uncertain_count": 0,
                    "duration_weighted_ms": 0,
                    "weight": 0,
                },
            )
            hour_summary["count"] += count
            hour_summary["uncertain_count"] += uncertain_count
            if duration and count:
                hour_summary["duration_weighted_ms"] += duration * count
                hour_summary["weight"] += count

            start = str(payload.get("window_start_at", ""))
            if len(start) >= 10:
                date_key = start[:10]
                day_summary = daily.setdefault(
                    date_key,
                    {"date": date_key, "count": 0, "uncertain_count": 0},
                )
                day_summary["count"] += count
                day_summary["uncertain_count"] += uncertain_count

                try:
                    from datetime import datetime

                    day_date = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    weekday_names = [
                        "Segunda-feira",
                        "Terça-feira",
                        "Quarta-feira",
                        "Quinta-feira",
                        "Sexta-feira",
                        "Sábado",
                        "Domingo",
                    ]
                    weekday = weekday_names[day_date.weekday()]
                    weekday_summary = weekdays.setdefault(
                        weekday,
                        {"weekday": weekday, "count": 0, "days": set()},
                    )
                    weekday_summary["count"] += count
                    weekday_summary["days"].add(date_key)
                except ValueError:
                    pass

        hourly_rows = []
        for hour_key in sorted(hourly):
            row = hourly[hour_key]
            weighted = row["duration_weighted_ms"]
            weight = row["weight"]
            hourly_rows.append(
                {
                    "hour": hour_key,
                    "count": row["count"],
                    "uncertain_count": row["uncertain_count"],
                    "duration_avg_ms": round(weighted / weight) if weight else None,
                }
            )

        duration_avg_ms = round(duration_total / duration_weight) if duration_weight else None
        daily_rows = sorted(
            (
                {
                    "date": row["date"],
                    "count": row["count"],
                    "uncertain_count": row["uncertain_count"],
                }
                for row in daily.values()
            ),
            key=lambda row: row["date"],
        )
        weekday_rows = []
        for weekday, row in weekdays.items():
            weekday_rows.append(
                {
                    "weekday": weekday,
                    "count": row["count"],
                    "average_per_day": round(row["count"] / len(row["days"]), 1),
                }
            )
        weekday_rows.sort(key=lambda row: row["weekday"])

        peak_hour = max(hourly_rows, key=lambda row: row["count"]) if hourly_rows else None
        peak_day = max(daily_rows, key=lambda row: row["count"]) if daily_rows else None
        busiest_weekday = (
            max(weekday_rows, key=lambda row: row["average_per_day"])
            if weekday_rows
            else None
        )
        average_daily_count = (
            round(sum(row["count"] for row in daily_rows) / len(daily_rows), 1)
            if daily_rows
            else None
        )
        return {
            "source": self.source,
            "demonstration": demonstration,
            "summary": {
                "total_count": total_count,
                "uncertain_count": uncertain,
                "duration_avg_ms": duration_avg_ms,
                "duration_avg_minutes": (
                    round(duration_avg_ms / 60000, 1) if duration_avg_ms is not None else None
                ),
                "metric_events": len(events),
            },
            "by_event": by_event,
            "zones": zones,
            "hourly": hourly_rows,
            "daily": daily_rows,
            "weekdays": weekday_rows,
            "insights": {
                "peak_hour": peak_hour,
                "peak_day": peak_day,
                "busiest_weekday": busiest_weekday,
                "average_daily_count": average_daily_count,
            },
        }
