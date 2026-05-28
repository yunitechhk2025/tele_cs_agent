import asyncio
import contextvars
import csv
import html
import io
import json
import logging
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import (
    Conversation,
    ConversationTurnMetric,
    ConversationTurnStepMetric,
    LLMCallMetric,
    ObservabilityAlert,
    SceneGenerationRecord,
    SystemSetting,
    TelegramBot,
)
from app.services.conversation_monitoring import STAGE_LABELS

logger = logging.getLogger(__name__)
settings = get_settings()

OBSERVABILITY_ALERT_SETTINGS_KEY = "observability_alert_settings"

DEFAULT_ALERT_SETTINGS = {
    "text_first_response_p95_ms": 8000,
    "product_recommendation_first_response_p95_ms": 12000,
    "scene_failure_rate": 0.2,
    "llm_failure_rate": 0.1,
    "turn_failure_rate": 0.05,
    "rag_empty_rate": 0.4,
    "profile_handoff_rate": 0.15,
}

HANDOFF_RESPONSE_KINDS = {
    "handoff",
    "profile_handoff",
    "complaint_handoff",
    "human_only_wait",
}

INTENT_LABELS = {
    "general_question": "普通问答",
    "product_recommendation": "商品推荐",
    "product_intro": "商品详情",
    "scene_image_request": "场景图",
    "scene_image_confirmation": "场景图确认",
    "file_request": "文件请求",
    "human_handoff": "转人工",
    "quote_handoff": "报价转人工",
    "complaint": "投诉",
    "unknown": "未知意图",
    "": "未识别意图",
}

_context_conversation_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "observability_conversation_id",
    default=None,
)
_context_turn_metric_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "observability_turn_metric_id",
    default=None,
)


def set_observability_context(
    conversation_id: int | None,
    turn_metric_id: int | None,
) -> tuple[contextvars.Token, contextvars.Token]:
    return (
        _context_conversation_id.set(conversation_id),
        _context_turn_metric_id.set(turn_metric_id),
    )


def reset_observability_context(tokens: tuple[contextvars.Token, contextvars.Token] | None) -> None:
    if not tokens:
        return
    conv_token, metric_token = tokens
    _context_conversation_id.reset(conv_token)
    _context_turn_metric_id.reset(metric_token)


def _round_rate(value: float) -> float:
    return round(float(value or 0.0), 4)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return _round_rate(numerator / denominator)


def percentile(values: list[int | None], percent: int) -> int | None:
    clean = sorted(int(value) for value in values if value is not None)
    if not clean:
        return None
    rank = max(1, min(len(clean), int((percent / 100) * len(clean) + 0.999999)))
    return clean[rank - 1]


def _avg(values: list[int | None]) -> int:
    clean = [int(value) for value in values if value is not None]
    if not clean:
        return 0
    return int(sum(clean) / len(clean))


def _safe_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _duration_values(rows: list[dict[str, Any]], field: str) -> list[int | None]:
    return [_get(row, field) for row in rows]


def _stage_label(stage_key: str, fallback: str = "") -> str:
    if stage_key in STAGE_LABELS:
        return STAGE_LABELS[stage_key]
    return fallback or stage_key


def _intent_label(intent: str) -> str:
    return INTENT_LABELS.get(intent or "", intent or "未识别意图")


def _unique_conversation_ids(rows: list[dict[str, Any]], *, limit: int = 10) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for row in rows:
        value = _get(row, "conversation_id")
        if value is None:
            continue
        try:
            conversation_id = int(value)
        except (TypeError, ValueError):
            continue
        if conversation_id in seen:
            continue
        seen.add(conversation_id)
        ids.append(conversation_id)
        if len(ids) >= limit:
            break
    return ids


def _slowest_conversation_ids(
    rows: list[dict[str, Any]],
    field: str,
    *,
    limit: int = 10,
) -> list[int]:
    sortable = [row for row in rows if _get(row, field) is not None and _get(row, "conversation_id") is not None]
    sortable.sort(key=lambda row: int(_get(row, field) or 0), reverse=True)
    return _unique_conversation_ids(sortable, limit=limit)


def _rag_empty_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    empty_steps: list[dict[str, Any]] = []
    for step in steps:
        if str(_get(step, "stage_key", "")) != "knowledge_retrieval":
            continue
        metadata = _safe_json_dict(_get(step, "metadata_json", "{}"))
        try:
            retrieved_chars = int(metadata.get("retrieved_chars") or 0)
        except (TypeError, ValueError):
            retrieved_chars = 0
        if retrieved_chars <= 0:
            empty_steps.append(step)
    return empty_steps


def build_observability_summary(
    turns: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    total_turns = len(turns)
    success_count = sum(1 for row in turns if bool(_get(row, "success", True)))
    failed_count = total_turns - success_count

    first_response_values = _duration_values(turns, "first_response_ms")
    total_values = _duration_values(turns, "total_ms")
    text_first_response_values = [
        _get(row, "first_response_ms")
        for row in turns
        if str(_get(row, "response_kind", "")) in {"text", "text_draft"}
    ]
    product_rec_first_response_values = [
        _get(row, "first_response_ms")
        for row in turns
        if str(_get(row, "primary_intent", "")) == "product_recommendation"
        or str(_get(row, "response_kind", "")).startswith("product_recommendation")
    ]

    handoff_count = sum(1 for row in turns if str(_get(row, "response_kind", "")) in HANDOFF_RESPONSE_KINDS)
    profile_handoff_count = sum(1 for row in turns if str(_get(row, "response_kind", "")) == "profile_handoff")

    rag_steps = [step for step in steps if str(_get(step, "stage_key", "")) == "knowledge_retrieval"]
    rag_empty_rows = _rag_empty_steps(steps)
    rag_empty_count = len(rag_empty_rows)

    llm_failure_count = sum(1 for row in llm_calls if not bool(_get(row, "success", True)))
    scene_failure_count = sum(1 for row in scenes if str(_get(row, "status", "")) == "failed")

    stage_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        stage_groups[str(_get(step, "stage_key", ""))].append(step)
    stage_metrics = []
    for stage_key, rows in stage_groups.items():
        durations = _duration_values(rows, "duration_ms")
        labels = [str(_get(row, "stage_label", "")) for row in rows if str(_get(row, "stage_label", ""))]
        stage_metrics.append({
            "stage_key": stage_key,
            "stage_label": _stage_label(stage_key, labels[0] if labels else ""),
            "count": len(rows),
            "avg_ms": _avg(durations),
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
            "p99_ms": percentile(durations, 99),
            "failed_count": sum(1 for row in rows if not bool(_get(row, "success", True))),
        })
    stage_metrics.sort(key=lambda item: (item.get("p95_ms") or 0, item.get("count") or 0), reverse=True)

    llm_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for call in llm_calls:
        key = (str(_get(call, "operation", "")), str(_get(call, "model", "")))
        llm_groups[key].append(call)
    llm_metrics = []
    for (operation, model), rows in llm_groups.items():
        durations = _duration_values(rows, "duration_ms")
        failed_rows = [row for row in rows if not bool(_get(row, "success", True))]
        last_error = ""
        if failed_rows:
            last_error = str(_get(failed_rows[-1], "error_message", "") or _get(failed_rows[-1], "error_type", ""))
        llm_metrics.append({
            "operation": operation,
            "model": model,
            "count": len(rows),
            "failed_count": len(failed_rows),
            "failure_rate": _safe_ratio(len(failed_rows), len(rows)),
            "avg_ms": _avg(durations),
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
            "p99_ms": percentile(durations, 99),
            "last_error": last_error[:500],
        })
    llm_metrics.sort(key=lambda item: (item["failed_count"], item["count"]), reverse=True)

    recent_failures: list[dict[str, Any]] = []
    for row in turns:
        if bool(_get(row, "success", True)):
            continue
        recent_failures.append({
            "source": "turn",
            "conversation_id": _get(row, "conversation_id"),
            "turn_metric_id": _get(row, "id"),
            "language": str(_get(row, "language", "")),
            "primary_intent": str(_get(row, "primary_intent", "")),
            "response_kind": str(_get(row, "response_kind", "")),
            "error_message": str(_get(row, "error_message", "")),
            "created_at": _dt(_get(row, "started_at")),
        })
    for scene in scenes:
        if str(_get(scene, "status", "")) != "failed":
            continue
        recent_failures.append({
            "source": "scene",
            "conversation_id": _get(scene, "conversation_id"),
            "turn_metric_id": None,
            "language": "",
            "primary_intent": "scene_image_request",
            "response_kind": "scene_failed",
            "error_message": str(_get(scene, "error_message", "")),
            "created_at": _dt(_get(scene, "created_at")),
        })
    recent_failures.sort(key=lambda item: item.get("created_at") or datetime.min, reverse=True)

    text_turns = [
        row for row in turns
        if str(_get(row, "response_kind", "")) in {"text", "text_draft"}
    ]
    product_turns = [
        row for row in turns
        if str(_get(row, "primary_intent", "")) == "product_recommendation"
        or str(_get(row, "response_kind", "")).startswith("product_recommendation")
    ]
    alert_samples = {
        "text_first_response_p95_ms": _slowest_conversation_ids(text_turns, "first_response_ms"),
        "product_recommendation_first_response_p95_ms": _slowest_conversation_ids(product_turns, "first_response_ms"),
        "turn_failure_rate": _unique_conversation_ids([row for row in turns if not bool(_get(row, "success", True))]),
        "profile_handoff_rate": _unique_conversation_ids([
            row for row in turns if str(_get(row, "response_kind", "")) == "profile_handoff"
        ]),
        "rag_empty_rate": _unique_conversation_ids(rag_empty_rows),
        "llm_failure_rate": _unique_conversation_ids([
            row for row in llm_calls if not bool(_get(row, "success", True))
        ]),
        "scene_failure_rate": _unique_conversation_ids([
            row for row in scenes if str(_get(row, "status", "")) == "failed"
        ]),
    }

    kpis = {
        "total_turns": total_turns,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": _safe_ratio(success_count, total_turns),
        "failure_rate": _safe_ratio(failed_count, total_turns),
        "first_response_p50_ms": percentile(first_response_values, 50),
        "first_response_p95_ms": percentile(first_response_values, 95),
        "first_response_p99_ms": percentile(first_response_values, 99),
        "total_p50_ms": percentile(total_values, 50),
        "total_p95_ms": percentile(total_values, 95),
        "total_p99_ms": percentile(total_values, 99),
        "text_first_response_p95_ms": percentile(text_first_response_values, 95),
        "product_recommendation_first_response_p95_ms": percentile(product_rec_first_response_values, 95),
        "handoff_count": handoff_count,
        "handoff_rate": _safe_ratio(handoff_count, total_turns),
        "profile_handoff_count": profile_handoff_count,
        "profile_handoff_rate": _safe_ratio(profile_handoff_count, total_turns),
        "rag_lookup_count": len(rag_steps),
        "rag_empty_count": rag_empty_count,
        "rag_empty_rate": _safe_ratio(rag_empty_count, len(rag_steps)),
        "llm_call_count": len(llm_calls),
        "llm_failure_count": llm_failure_count,
        "llm_failure_rate": _safe_ratio(llm_failure_count, len(llm_calls)),
        "scene_generation_count": len(scenes),
        "scene_failure_count": scene_failure_count,
        "scene_failure_rate": _safe_ratio(scene_failure_count, len(scenes)),
    }
    return {
        "kpis": kpis,
        "stage_metrics": stage_metrics,
        "slowest_stages": stage_metrics[:5],
        "llm_metrics": llm_metrics,
        "recent_failures": recent_failures[:20],
        "alert_samples": alert_samples,
    }


def _window_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def _alert(
    metric_key: str,
    severity: str,
    title: str,
    message: str,
    observed_value: float,
    threshold_value: float,
    window_start: datetime,
    window_end: datetime,
    scope_key: str,
    sample_conversation_ids: list[int] | None = None,
) -> dict[str, Any]:
    samples = [int(item) for item in (sample_conversation_ids or [])[:10]]
    return {
        "severity": severity,
        "metric_key": metric_key,
        "title": title,
        "message": message,
        "observed_value": float(observed_value or 0),
        "threshold_value": float(threshold_value or 0),
        "window_start": window_start,
        "window_end": window_end,
        "status": "open",
        "dedupe_key": f"{metric_key}:{_window_key(window_start)}:{_window_key(window_end)}:{scope_key}",
        "sample_conversation_ids_json": json.dumps(samples, ensure_ascii=False),
        "sample_count": len(samples),
    }


def evaluate_alert_candidates(
    summary: dict[str, Any],
    alert_settings: dict[str, Any] | None,
    *,
    window_start: datetime,
    window_end: datetime,
    scope_key: str,
) -> list[dict[str, Any]]:
    settings_map = {**DEFAULT_ALERT_SETTINGS, **(alert_settings or {})}
    kpis = summary.get("kpis") or {}
    alert_samples = summary.get("alert_samples") or {}
    checks = [
        (
            "text_first_response_p95_ms",
            kpis.get("text_first_response_p95_ms"),
            settings_map["text_first_response_p95_ms"],
            "warning",
            "普通文本首响 P95 过高",
            "普通文本回复首响延迟超过阈值。",
        ),
        (
            "product_recommendation_first_response_p95_ms",
            kpis.get("product_recommendation_first_response_p95_ms"),
            settings_map["product_recommendation_first_response_p95_ms"],
            "warning",
            "商品推荐首响 P95 过高",
            "商品推荐链路首响延迟超过阈值。",
        ),
        (
            "scene_failure_rate",
            kpis.get("scene_failure_rate"),
            settings_map["scene_failure_rate"],
            "critical",
            "场景图失败率过高",
            "场景图生成失败率超过阈值。",
        ),
        (
            "llm_failure_rate",
            kpis.get("llm_failure_rate"),
            settings_map["llm_failure_rate"],
            "critical",
            "LLM 调用失败率过高",
            "LLM、Embedding 或图片模型调用失败率超过阈值。",
        ),
        (
            "turn_failure_rate",
            kpis.get("failure_rate"),
            settings_map["turn_failure_rate"],
            "warning",
            "对话处理失败率过高",
            "客户消息处理失败率超过阈值。",
        ),
        (
            "rag_empty_rate",
            kpis.get("rag_empty_rate"),
            settings_map["rag_empty_rate"],
            "warning",
            "RAG 空命中率过高",
            "知识库检索空命中率超过阈值。",
        ),
        (
            "profile_handoff_rate",
            kpis.get("profile_handoff_rate"),
            settings_map["profile_handoff_rate"],
            "warning",
            "疑似误转人工占比过高",
            "profile_handoff 占比超过阈值，需要检查商品需求解析。",
        ),
    ]
    alerts: list[dict[str, Any]] = []
    for metric_key, observed, threshold, severity, title, message in checks:
        if observed is None:
            continue
        try:
            observed_num = float(observed)
            threshold_num = float(threshold)
        except (TypeError, ValueError):
            continue
        if observed_num > threshold_num:
            sample_ids = alert_samples.get(metric_key) or []
            alerts.append(_alert(
                metric_key,
                severity,
                title,
                message,
                observed_num,
                threshold_num,
                window_start,
                window_end,
                scope_key,
                sample_ids,
            ))
    return alerts


def _trend_granularity(range_key: str | None) -> str:
    return "hour" if str(range_key or "24h") == "24h" else "day"


def _bucket_start(dt: datetime, granularity: str) -> datetime:
    if granularity == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_label(dt: datetime, granularity: str) -> str:
    return dt.strftime("%m-%d %H:00") if granularity == "hour" else dt.strftime("%m-%d")


def build_observability_stage_trends(
    steps: list[dict[str, Any]],
    *,
    range_key: str = "24h",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    granularity = _trend_granularity(range_key)
    grouped: dict[str, dict[str, dict[datetime, list[int]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for step in steps:
        started_at = _dt(_get(step, "started_at"))
        duration = _get(step, "duration_ms")
        if started_at is None or duration is None:
            continue
        if window_start and started_at < window_start:
            continue
        if window_end and started_at > window_end:
            continue
        try:
            duration_ms = int(duration)
        except (TypeError, ValueError):
            continue
        intent = str(_get(step, "primary_intent", "") or "unknown")
        stage_key = str(_get(step, "stage_key", "") or "unknown")
        grouped[intent][stage_key][_bucket_start(started_at, granularity)].append(duration_ms)

    intent_groups: list[dict[str, Any]] = []
    for intent, stage_map in grouped.items():
        stages: list[dict[str, Any]] = []
        for stage_key, bucket_map in stage_map.items():
            all_values = [value for values in bucket_map.values() for value in values]
            points = []
            for bucket, values in sorted(bucket_map.items(), key=lambda item: item[0]):
                points.append({
                    "bucket_start": bucket,
                    "bucket_label": _bucket_label(bucket, granularity),
                    "count": len(values),
                    "avg_ms": _avg(values),
                    "p50_ms": percentile(values, 50),
                    "p95_ms": percentile(values, 95),
                    "p99_ms": percentile(values, 99),
                })
            stages.append({
                "stage_key": stage_key,
                "stage_label": _stage_label(stage_key),
                "count": len(all_values),
                "avg_ms": _avg(all_values),
                "p50_ms": percentile(all_values, 50),
                "p95_ms": percentile(all_values, 95),
                "p99_ms": percentile(all_values, 99),
                "points": points,
            })
        stages.sort(key=lambda item: (item.get("p95_ms") or 0, item.get("count") or 0), reverse=True)
        intent_groups.append({
            "intent": intent,
            "intent_label": _intent_label(intent),
            "stages": stages,
        })
    intent_groups.sort(key=lambda item: sum(stage["count"] for stage in item["stages"]), reverse=True)
    return {
        "granularity": granularity,
        "window_start": window_start,
        "window_end": window_end,
        "intents": intent_groups,
    }


def _csv_text(headers: list[str], rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _export_value(row.get(key)) for key in headers})
    return out.getvalue()


def _export_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def build_observability_export_zip(
    summary: dict[str, Any],
    alerts: list[Any],
) -> bytes:
    kpis = summary.get("kpis") or {}
    kpi_rows = [{"metric": key, "value": value} for key, value in kpis.items()]
    alert_rows = []
    for alert in alerts:
        alert_rows.append({
            "id": _get(alert, "id"),
            "severity": _get(alert, "severity", ""),
            "metric_key": _get(alert, "metric_key", ""),
            "title": _get(alert, "title", ""),
            "message": _get(alert, "message", ""),
            "observed_value": _get(alert, "observed_value", ""),
            "threshold_value": _get(alert, "threshold_value", ""),
            "status": _get(alert, "status", ""),
            "sample_conversation_ids_json": _get(alert, "sample_conversation_ids_json", "[]"),
            "sample_count": _get(alert, "sample_count", 0),
            "window_start": _get(alert, "window_start"),
            "window_end": _get(alert, "window_end"),
            "created_at": _get(alert, "created_at"),
        })

    files = {
        "kpis.csv": _csv_text(["metric", "value"], kpi_rows),
        "stage_metrics.csv": _csv_text(
            ["stage_key", "stage_label", "count", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "failed_count"],
            summary.get("stage_metrics") or [],
        ),
        "llm_metrics.csv": _csv_text(
            ["operation", "model", "count", "failed_count", "failure_rate", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "last_error"],
            summary.get("llm_metrics") or [],
        ),
        "alerts.csv": _csv_text(
            [
                "id", "severity", "metric_key", "title", "message", "observed_value", "threshold_value",
                "status", "sample_conversation_ids_json", "sample_count", "window_start", "window_end", "created_at",
            ],
            alert_rows,
        ),
        "recent_failures.csv": _csv_text(
            ["source", "conversation_id", "turn_metric_id", "language", "primary_intent", "response_kind", "error_message", "created_at"],
            summary.get("recent_failures") or [],
        ),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, text in files.items():
            zf.writestr(filename, text.encode("utf-8-sig"))
    return out.getvalue()


def build_observability_export_filename(
    *,
    range_key: str,
    bot_id: int | None = None,
    language: str | None = None,
    intent: str | None = None,
    response_kind: str | None = None,
) -> str:
    parts = ["observability", range_key]
    if bot_id is not None:
        parts.append(f"bot-{bot_id}")
    if language:
        parts.append(language)
    if intent:
        parts.append(intent)
    if response_kind:
        parts.append(response_kind)
    parts.append(datetime.utcnow().strftime("%Y%m%d%H%M%S"))
    safe = ["".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in part) for part in parts]
    return "-".join(safe) + ".zip"


def resolve_time_range(range_key: str | None) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    mapping = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    delta = mapping.get(str(range_key or "24h"), mapping["24h"])
    return now - delta, now


def _scope_key(
    *,
    bot_id: int | None = None,
    language: str | None = None,
    intent: str | None = None,
    response_kind: str | None = None,
) -> str:
    return "|".join([
        f"bot={bot_id or 'all'}",
        f"language={language or 'all'}",
        f"intent={intent or 'all'}",
        f"response_kind={response_kind or 'all'}",
    ])


def _turn_to_row(metric: ConversationTurnMetric, bot_id: int | None, language: str | None) -> dict[str, Any]:
    return {
        "id": metric.id,
        "conversation_id": metric.conversation_id,
        "bot_id": bot_id,
        "language": language or "",
        "primary_intent": metric.primary_intent or "",
        "response_kind": metric.response_kind or "",
        "first_response_ms": metric.first_response_ms,
        "total_ms": metric.total_ms,
        "success": metric.success,
        "error_message": metric.error_message or "",
        "started_at": metric.started_at,
    }


def _step_to_row(step: ConversationTurnStepMetric) -> dict[str, Any]:
    return {
        "turn_metric_id": step.turn_metric_id,
        "conversation_id": step.conversation_id,
        "stage_key": step.stage_key or "",
        "stage_label": _stage_label(step.stage_key or "", step.stage_label or ""),
        "duration_ms": step.duration_ms,
        "success": step.success,
        "metadata_json": step.metadata_json or "{}",
        "started_at": step.started_at,
    }


def _llm_to_row(call: LLMCallMetric) -> dict[str, Any]:
    return {
        "operation": call.operation or "",
        "model": call.model or "",
        "duration_ms": call.duration_ms,
        "success": call.success,
        "error_type": call.error_type or "",
        "error_message": call.error_message or "",
        "conversation_id": call.conversation_id,
        "turn_metric_id": call.turn_metric_id,
        "created_at": call.created_at,
    }


def _scene_to_row(scene: SceneGenerationRecord) -> dict[str, Any]:
    return {
        "conversation_id": scene.conversation_id,
        "status": scene.status or "",
        "duration_ms": scene.duration_ms,
        "error_message": scene.error_message or "",
        "created_at": scene.created_at,
    }


async def load_observability_summary(
    db: AsyncSession,
    *,
    range_key: str = "24h",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    bot_id: int | None = None,
    language: str | None = None,
    intent: str | None = None,
    response_kind: str | None = None,
) -> dict[str, Any]:
    if window_start is None or window_end is None:
        window_start, window_end = resolve_time_range(range_key)
    stmt = (
        select(ConversationTurnMetric, Conversation.bot_id, Conversation.language)
        .join(Conversation, Conversation.id == ConversationTurnMetric.conversation_id)
        .where(
            ConversationTurnMetric.started_at >= window_start,
            ConversationTurnMetric.started_at <= window_end,
        )
    )
    if bot_id is not None:
        stmt = stmt.where(Conversation.bot_id == bot_id)
    if language:
        stmt = stmt.where(Conversation.language == language)
    if intent:
        stmt = stmt.where(ConversationTurnMetric.primary_intent == intent)
    if response_kind:
        stmt = stmt.where(ConversationTurnMetric.response_kind == response_kind)
    result = await db.execute(stmt.order_by(desc(ConversationTurnMetric.started_at), desc(ConversationTurnMetric.id)))
    turn_rows_raw = result.all()
    turns = [_turn_to_row(metric, row_bot_id, row_language) for metric, row_bot_id, row_language in turn_rows_raw]
    turn_ids = [int(row["id"]) for row in turns if row.get("id") is not None]
    conversation_ids = sorted({int(row["conversation_id"]) for row in turns if row.get("conversation_id") is not None})

    steps: list[dict[str, Any]] = []
    if turn_ids:
        step_result = await db.execute(
            select(ConversationTurnStepMetric)
            .where(ConversationTurnStepMetric.turn_metric_id.in_(turn_ids))
            .order_by(ConversationTurnStepMetric.stage_key)
        )
        steps = [_step_to_row(step) for step in step_result.scalars().all()]

    llm_stmt = select(LLMCallMetric).where(
        LLMCallMetric.created_at >= window_start,
        LLMCallMetric.created_at <= window_end,
    )
    if bot_id is not None or language or intent or response_kind:
        if conversation_ids:
            llm_stmt = llm_stmt.where(LLMCallMetric.conversation_id.in_(conversation_ids))
        else:
            llm_stmt = llm_stmt.where(LLMCallMetric.id == -1)
    llm_result = await db.execute(llm_stmt.order_by(LLMCallMetric.created_at))
    llm_calls = [_llm_to_row(call) for call in llm_result.scalars().all()]

    scene_stmt = select(SceneGenerationRecord).where(
        SceneGenerationRecord.created_at >= window_start,
        SceneGenerationRecord.created_at <= window_end,
    )
    if bot_id is not None or language or intent or response_kind:
        if conversation_ids:
            scene_stmt = scene_stmt.where(SceneGenerationRecord.conversation_id.in_(conversation_ids))
        else:
            scene_stmt = scene_stmt.where(SceneGenerationRecord.id == -1)
    scene_result = await db.execute(scene_stmt.order_by(SceneGenerationRecord.created_at))
    scenes = [_scene_to_row(scene) for scene in scene_result.scalars().all()]
    return build_observability_summary(turns, steps, llm_calls, scenes)


async def load_observability_stage_trends(
    db: AsyncSession,
    *,
    range_key: str = "24h",
    bot_id: int | None = None,
    language: str | None = None,
    intent: str | None = None,
    response_kind: str | None = None,
) -> dict[str, Any]:
    window_start, window_end = resolve_time_range(range_key)
    stmt = (
        select(ConversationTurnStepMetric, ConversationTurnMetric.primary_intent)
        .join(ConversationTurnMetric, ConversationTurnMetric.id == ConversationTurnStepMetric.turn_metric_id)
        .join(Conversation, Conversation.id == ConversationTurnMetric.conversation_id)
        .where(
            ConversationTurnStepMetric.started_at >= window_start,
            ConversationTurnStepMetric.started_at <= window_end,
        )
    )
    if bot_id is not None:
        stmt = stmt.where(Conversation.bot_id == bot_id)
    if language:
        stmt = stmt.where(Conversation.language == language)
    if intent:
        stmt = stmt.where(ConversationTurnMetric.primary_intent == intent)
    if response_kind:
        stmt = stmt.where(ConversationTurnMetric.response_kind == response_kind)
    result = await db.execute(stmt.order_by(ConversationTurnStepMetric.started_at))
    rows: list[dict[str, Any]] = []
    for step, primary_intent in result.all():
        row = _step_to_row(step)
        row["primary_intent"] = primary_intent or "unknown"
        rows.append(row)
    return build_observability_stage_trends(
        rows,
        range_key=range_key,
        window_start=window_start,
        window_end=window_end,
    )


async def load_alert_settings(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(SystemSetting, OBSERVABILITY_ALERT_SETTINGS_KEY)
    if not row or not row.value:
        return dict(DEFAULT_ALERT_SETTINGS)
    try:
        parsed = json.loads(row.value)
    except Exception:
        return dict(DEFAULT_ALERT_SETTINGS)
    if not isinstance(parsed, dict):
        return dict(DEFAULT_ALERT_SETTINGS)
    out = dict(DEFAULT_ALERT_SETTINGS)
    for key in DEFAULT_ALERT_SETTINGS:
        if key in parsed:
            out[key] = parsed[key]
    return out


async def save_alert_settings(db: AsyncSession, updates: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_ALERT_SETTINGS)
    for key, default in DEFAULT_ALERT_SETTINGS.items():
        value = updates.get(key, default)
        try:
            out[key] = float(value) if isinstance(default, float) else int(value)
        except (TypeError, ValueError):
            out[key] = default
    existing = await db.get(SystemSetting, OBSERVABILITY_ALERT_SETTINGS_KEY)
    value = json.dumps(out, ensure_ascii=False)
    if existing:
        existing.value = value
    else:
        db.add(SystemSetting(key=OBSERVABILITY_ALERT_SETTINGS_KEY, value=value))
    await db.commit()
    return out


async def list_alerts(db: AsyncSession, *, status: str | None = None, limit: int = 100) -> list[ObservabilityAlert]:
    stmt = select(ObservabilityAlert).order_by(desc(ObservabilityAlert.created_at), desc(ObservabilityAlert.id)).limit(limit)
    if status:
        stmt = stmt.where(ObservabilityAlert.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def acknowledge_alert(db: AsyncSession, alert_id: int) -> ObservabilityAlert | None:
    alert = await db.get(ObservabilityAlert, alert_id)
    if not alert:
        return None
    alert.status = "ack"
    alert.acknowledged_at = datetime.utcnow()
    await db.commit()
    await db.refresh(alert)
    return alert


async def record_llm_call(
    *,
    operation: str,
    provider: str,
    model: str,
    duration_ms: int,
    success: bool,
    error_type: str = "",
    error_message: str = "",
    conversation_id: int | None = None,
    turn_metric_id: int | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(LLMCallMetric(
                operation=operation[:100],
                provider=provider[:100],
                model=model[:200],
                duration_ms=max(0, int(duration_ms)),
                success=bool(success),
                error_type=(error_type or "")[:200],
                error_message=(error_message or "")[:2000],
                conversation_id=conversation_id if conversation_id is not None else _context_conversation_id.get(),
                turn_metric_id=turn_metric_id if turn_metric_id is not None else _context_turn_metric_id.get(),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record LLM call metric operation=%s model=%s", operation, model)


async def timed_llm_call(
    *,
    operation: str,
    provider: str,
    model: str,
    call,
) -> Any:
    started = time.perf_counter()
    try:
        result = await call()
    except Exception as exc:
        await record_llm_call(
            operation=operation,
            provider=provider,
            model=model,
            duration_ms=int((time.perf_counter() - started) * 1000),
            success=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    await record_llm_call(
        operation=operation,
        provider=provider,
        model=model,
        duration_ms=int((time.perf_counter() - started) * 1000),
        success=True,
    )
    return result


async def _persist_alert_candidates(db: AsyncSession, candidates: list[dict[str, Any]]) -> list[ObservabilityAlert]:
    created: list[ObservabilityAlert] = []
    for item in candidates:
        alert = ObservabilityAlert(**item)
        db.add(alert)
        try:
            await db.commit()
            await db.refresh(alert)
            created.append(alert)
        except IntegrityError:
            await db.rollback()
        except Exception:
            await db.rollback()
            logger.exception("Failed to persist observability alert metric=%s", item.get("metric_key"))
    return created


async def _send_alert_to_telegram(alert: ObservabilityAlert) -> bool:
    from app.services import bot_manager

    targets: list[tuple[Any, str]] = []
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(TelegramBot).where(TelegramBot.is_active == True))
            for bot in result.scalars().all():
                if not bot.admin_chat_id:
                    continue
                bot_instance = bot_manager.get_bot_instance(bot.id)
                if bot_instance:
                    targets.append((bot_instance, bot.admin_chat_id))
        if not targets and settings.ADMIN_CHAT_ID:
            bot_instance = bot_manager.get_any_bot_instance()
            if bot_instance:
                targets.append((bot_instance, settings.ADMIN_CHAT_ID))
        if not targets:
            logger.warning("No Telegram admin target available for observability alert %s", alert.id)
            return False

        severity = "CRITICAL" if alert.severity == "critical" else "WARNING"
        sample_ids = []
        try:
            parsed_samples = json.loads(alert.sample_conversation_ids_json or "[]")
            if isinstance(parsed_samples, list):
                sample_ids = [int(item) for item in parsed_samples[:3]]
        except Exception:
            sample_ids = []
        sample_line = ""
        if sample_ids:
            sample_line = "\nSamples: " + ", ".join(f"<code>#{item}</code>" for item in sample_ids)
        text = (
            f"<b>{html.escape(severity)} observability alert</b>\n"
            f"Metric: <code>{html.escape(alert.metric_key)}</code>\n"
            f"{html.escape(alert.title)}\n\n"
            f"{html.escape(alert.message)}\n"
            f"Observed: <code>{alert.observed_value:.4f}</code>\n"
            f"Threshold: <code>{alert.threshold_value:.4f}</code>\n"
            f"Window: <code>{alert.window_start:%Y-%m-%d %H:%M}</code> - "
            f"<code>{alert.window_end:%Y-%m-%d %H:%M}</code>"
            f"{sample_line}"
        )
        sent = False
        seen: set[tuple[int, str]] = set()
        for bot_instance, chat_id in targets:
            key = (id(bot_instance), str(chat_id))
            if key in seen:
                continue
            seen.add(key)
            try:
                await bot_instance.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_notification=False)
                sent = True
            except Exception:
                logger.exception("Failed to send observability alert %s to Telegram chat %s", alert.id, chat_id)
        return sent
    except Exception:
        logger.exception("Failed to send observability alert %s", alert.id)
        return False


async def run_observability_alert_check(window_minutes: int = 15) -> int:
    window_end = datetime.utcnow()
    window_start = window_end - timedelta(minutes=window_minutes)
    scope = _scope_key()
    async with AsyncSessionLocal() as db:
        summary = await load_observability_summary(
            db,
            window_start=window_start,
            window_end=window_end,
        )
        settings_map = await load_alert_settings(db)
        candidates = evaluate_alert_candidates(
            summary,
            settings_map,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope,
        )
        alerts = await _persist_alert_candidates(db, candidates)

    sent_count = 0
    for alert in alerts:
        if await _send_alert_to_telegram(alert):
            sent_count += 1
            try:
                async with AsyncSessionLocal() as db:
                    current = await db.get(ObservabilityAlert, alert.id)
                    if current:
                        current.sent_at = datetime.utcnow()
                        await db.commit()
            except Exception:
                logger.exception("Failed to mark observability alert %s as sent", alert.id)
    return sent_count


async def observability_alert_loop(interval_seconds: int = 300, window_minutes: int = 15) -> None:
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await run_observability_alert_check(window_minutes=window_minutes)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Observability alert check failed")
    except asyncio.CancelledError:
        logger.info("Observability alert loop cancelled")
        raise
