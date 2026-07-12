"""商品推荐准确率离线评测服务。

该模块不直接调用 LLM。它把经过人工审核的 golden case 与一次真实链路导出的结果
进行比对，避免 CI 因模型波动、网络或计费而产生不稳定结论。业务侧可以先标注需求、
语言和可接受商品，再用同一评分器比较模型、提示词或召回策略的效果。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROFILE_DIMENSIONS = (
    "categories",
    "spaces",
    "styles",
    "colors",
    "materials",
    "brands",
)
HANDOFF_INTENTS = {"quote_handoff", "human_handoff", "complaint"}
HANDOFF_RESPONSE_KINDS = {
    "handoff",
    "profile_handoff",
    "complaint_handoff",
    "human_only_wait",
}


def _string_list(value: Any) -> list[str]:
    """把评测文件中的标量或数组收敛为去重字符串列表。"""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    """读取 JSON 或 JSONL 评测结果，兼容人工导出和自动回放两种格式。"""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            rows.append(value)
        return rows

    value = json.loads(raw)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object or array")
    if isinstance(value.get("cases"), list):
        return [item for item in value["cases"] if isinstance(item, dict)]
    if isinstance(value.get("results"), list):
        return [item for item in value["results"] if isinstance(item, dict)]
    if value.get("case_id"):
        return [value]
    return [
        {"case_id": case_id, **_as_mapping(result)}
        for case_id, result in value.items()
        if isinstance(result, dict)
    ]


def load_recommendation_evaluation_cases(path: Path) -> list[dict[str, Any]]:
    """加载并校验 golden cases，确保每个案例有稳定且唯一的 case_id。"""
    cases = _load_json_rows(path)
    seen_case_ids: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"{path}: case #{index} is missing case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"{path}: duplicate case_id {case_id!r}")
        input_data = _as_mapping(case.get("input"))
        expected = _as_mapping(case.get("expected"))
        if not str(input_data.get("message") or "").strip():
            raise ValueError(f"{path}: case {case_id!r} is missing input.message")
        if not str(expected.get("intent") or "").strip():
            raise ValueError(f"{path}: case {case_id!r} is missing expected.intent")
        seen_case_ids.add(case_id)
        normalized_cases.append(
            {
                **case,
                "case_id": case_id,
                "input": input_data,
                "expected": expected,
                "tags": _string_list(case.get("tags")),
            }
        )
    return normalized_cases


def load_recommendation_evaluation_results(path: Path) -> dict[str, dict[str, Any]]:
    """加载一次评测运行的结果，并拒绝会掩盖问题的重复 case_id。"""
    rows = _load_json_rows(path)
    results: dict[str, dict[str, Any]] = {}
    for index, result in enumerate(rows, start=1):
        case_id = str(result.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"{path}: result #{index} is missing case_id")
        if case_id in results:
            raise ValueError(f"{path}: duplicate result case_id {case_id!r}")
        results[case_id] = result
    return results


def _is_handoff(result: dict[str, Any]) -> bool:
    return (
        str(result.get("intent") or "") in HANDOFF_INTENTS
        or str(result.get("response_kind") or "") in HANDOFF_RESPONSE_KINDS
    )


def _expected_profile_values(expected: dict[str, Any]) -> dict[str, list[str]]:
    profile = _as_mapping(expected.get("profile"))
    return {dimension: _string_list(profile.get(dimension)) for dimension in PROFILE_DIMENSIONS}


def _product_keys(value: dict[str, Any], *, accepted: bool = False) -> set[str]:
    """读取品牌加外部编号的稳定商品键，并兼容早期仅 external id 的结果格式。"""
    prefix = "accepted" if accepted else "selected"
    keys = _string_list(value.get(f"{prefix}_product_keys"))
    if keys:
        return set(keys)
    return set(_string_list(value.get(f"{prefix}_product_id_exts")))


def _actual_profile_values(result: dict[str, Any]) -> dict[str, list[str]]:
    profile = _as_mapping(result.get("profile"))
    return {dimension: _string_list(profile.get(dimension)) for dimension in PROFILE_DIMENSIONS}


def _check_profile_constraints(
    expected: dict[str, Any], result: dict[str, Any]
) -> tuple[bool | None, int, int]:
    expected_values = _expected_profile_values(expected)
    actual_values = _actual_profile_values(result)
    expected_count = 0
    matched_count = 0
    for dimension, values in expected_values.items():
        for value in values:
            expected_count += 1
            if value in actual_values[dimension]:
                matched_count += 1
    if expected_count == 0:
        return None, 0, 0
    return matched_count == expected_count, matched_count, expected_count


def _check_hard_constraint_dimensions(
    expected: dict[str, Any], result: dict[str, Any]
) -> bool | None:
    expected_profile = _as_mapping(expected.get("profile"))
    expected_dimensions = _string_list(expected_profile.get("hard_constraints"))
    if not expected_dimensions:
        return None
    actual_dimensions = set(
        _string_list(_as_mapping(result.get("profile")).get("hard_constraints"))
    )
    return set(expected_dimensions).issubset(actual_dimensions)


def evaluate_recommendation_quality(
    cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """对一批推荐结果评分并返回可保存、可比较的结构化报告。

    评分只比较 golden case 明确标注过的字段。没有标注可接受商品的案例不会被计入
    商品 Top 3 指标，避免用猜测的商品答案污染真实基线。
    """
    counters = {
        "covered": 0,
        "intent_total": 0,
        "intent_matched": 0,
        "language_total": 0,
        "language_matched": 0,
        "profile_value_total": 0,
        "profile_value_matched": 0,
        "profile_case_total": 0,
        "profile_case_matched": 0,
        "hard_constraint_total": 0,
        "hard_constraint_matched": 0,
        "product_total": 0,
        "product_matched": 0,
        "forbidden_total": 0,
        "forbidden_violations": 0,
        "handoff_total": 0,
        "handoff_matched": 0,
        "refresh_total": 0,
        "refresh_matched": 0,
        "reference_total": 0,
        "reference_matched": 0,
        "case_passed": 0,
    }
    case_reports: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["case_id"]
        expected = _as_mapping(case.get("expected"))
        result = results.get(case_id)
        if result is None:
            case_reports.append(
                {
                    "case_id": case_id,
                    "tags": case.get("tags", []),
                    "status": "missing_result",
                    "passed": False,
                    "failed_checks": ["missing_result"],
                }
            )
            continue

        counters["covered"] += 1
        failed_checks: list[str] = []
        checks: dict[str, bool | None] = {}

        expected_intent = str(expected.get("intent") or "").strip()
        if expected_intent:
            counters["intent_total"] += 1
            intent_ok = str(result.get("intent") or "").strip() == expected_intent
            checks["intent"] = intent_ok
            if intent_ok:
                counters["intent_matched"] += 1
            else:
                failed_checks.append("intent")

        expected_language = str(_as_mapping(case.get("input")).get("language") or "").strip()
        if expected_language:
            counters["language_total"] += 1
            language_ok = str(result.get("language") or "").strip() == expected_language
            checks["language"] = language_ok
            if language_ok:
                counters["language_matched"] += 1
            else:
                failed_checks.append("language")

        profile_ok, profile_matched, profile_total = _check_profile_constraints(expected, result)
        checks["profile_constraints"] = profile_ok
        if profile_total:
            counters["profile_case_total"] += 1
            counters["profile_value_total"] += profile_total
            counters["profile_value_matched"] += profile_matched
            if profile_ok:
                counters["profile_case_matched"] += 1
            else:
                failed_checks.append("profile_constraints")

        hard_constraints_ok = _check_hard_constraint_dimensions(expected, result)
        checks["hard_constraint_dimensions"] = hard_constraints_ok
        if hard_constraints_ok is not None:
            counters["hard_constraint_total"] += 1
            if hard_constraints_ok:
                counters["hard_constraint_matched"] += 1
            else:
                failed_checks.append("hard_constraint_dimensions")

        accepted_product_ids = _product_keys(expected, accepted=True)
        selected_product_ids = _product_keys(result)
        if accepted_product_ids:
            counters["product_total"] += 1
            product_ok = bool(accepted_product_ids & selected_product_ids)
            checks["accepted_product_ids"] = product_ok
            if product_ok:
                counters["product_matched"] += 1
            else:
                failed_checks.append("accepted_product_ids")

        forbidden_product_ids = set(_string_list(expected.get("forbidden_product_keys"))) or set(
            _string_list(expected.get("forbidden_product_id_exts"))
        )
        if forbidden_product_ids:
            counters["forbidden_total"] += 1
            forbidden_ok = not bool(forbidden_product_ids & selected_product_ids)
            checks["forbidden_product_ids"] = forbidden_ok
            if not forbidden_ok:
                counters["forbidden_violations"] += 1
                failed_checks.append("forbidden_product_ids")

        if "should_handoff" in expected:
            counters["handoff_total"] += 1
            handoff_ok = _is_handoff(result) == bool(expected.get("should_handoff"))
            checks["handoff"] = handoff_ok
            if handoff_ok:
                counters["handoff_matched"] += 1
            else:
                failed_checks.append("handoff")

        if "is_recommendation_refresh" in expected:
            counters["refresh_total"] += 1
            actual_slots = _as_mapping(result.get("intent_slots"))
            refresh_ok = bool(actual_slots.get("is_recommendation_refresh")) == bool(
                expected.get("is_recommendation_refresh")
            )
            checks["recommendation_refresh"] = refresh_ok
            if refresh_ok:
                counters["refresh_matched"] += 1
            else:
                failed_checks.append("recommendation_refresh")

        expected_target = str(
            expected.get("target_product_key") or expected.get("target_product_id_ext") or ""
        ).strip()
        if expected_target:
            counters["reference_total"] += 1
            actual_target = str(
                result.get("target_product_key") or result.get("target_product_id_ext") or ""
            ).strip()
            reference_ok = actual_target == expected_target
            checks["product_reference"] = reference_ok
            if reference_ok:
                counters["reference_matched"] += 1
            else:
                failed_checks.append("product_reference")

        expected_response_kind = str(expected.get("response_kind") or "").strip()
        if expected_response_kind:
            response_kind_ok = str(result.get("response_kind") or "").strip() == expected_response_kind
            checks["response_kind"] = response_kind_ok
            if not response_kind_ok:
                failed_checks.append("response_kind")

        passed = not failed_checks
        if passed:
            counters["case_passed"] += 1
        case_reports.append(
            {
                "case_id": case_id,
                "tags": case.get("tags", []),
                "status": "passed" if passed else "failed",
                "passed": passed,
                "failed_checks": failed_checks,
                "checks": checks,
                "actual": {
                    "intent": result.get("intent", ""),
                    "language": result.get("language", ""),
                    "selected_product_keys": sorted(selected_product_ids),
                    "response_kind": result.get("response_kind", ""),
                },
            }
        )

    total_cases = len(cases)
    summary = {
        "total_cases": total_cases,
        "covered_cases": counters["covered"],
        "missing_result_count": total_cases - counters["covered"],
        "coverage_rate": _safe_ratio(counters["covered"], total_cases),
        "intent_accuracy": _safe_ratio(counters["intent_matched"], counters["intent_total"]),
        "language_accuracy": _safe_ratio(counters["language_matched"], counters["language_total"]),
        "profile_constraint_recall": _safe_ratio(
            counters["profile_value_matched"], counters["profile_value_total"]
        ),
        "profile_constraint_case_accuracy": _safe_ratio(
            counters["profile_case_matched"], counters["profile_case_total"]
        ),
        "hard_constraint_dimension_accuracy": _safe_ratio(
            counters["hard_constraint_matched"], counters["hard_constraint_total"]
        ),
        "product_top3_hit_rate": _safe_ratio(counters["product_matched"], counters["product_total"]),
        "forbidden_product_violation_rate": _safe_ratio(
            counters["forbidden_violations"], counters["forbidden_total"]
        ),
        "handoff_accuracy": _safe_ratio(counters["handoff_matched"], counters["handoff_total"]),
        "refresh_semantics_accuracy": _safe_ratio(
            counters["refresh_matched"], counters["refresh_total"]
        ),
        "product_reference_accuracy": _safe_ratio(
            counters["reference_matched"], counters["reference_total"]
        ),
        "case_pass_rate": _safe_ratio(counters["case_passed"], total_cases),
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "cases": case_reports,
    }


def compare_report_to_baseline(
    report: dict[str, Any], baseline: dict[str, Any], *, allowed_regression: float = 0.0
) -> list[str]:
    """比较当前报告与基线，只对双方都已测得的数值指标判定回归。"""
    tolerance = max(0.0, float(allowed_regression))
    current_summary = _as_mapping(report.get("summary"))
    baseline_summary = _as_mapping(baseline.get("summary"))
    regressions: list[str] = []
    for metric, baseline_value in baseline_summary.items():
        current_value = current_summary.get(metric)
        if not isinstance(baseline_value, (int, float)) or not isinstance(current_value, (int, float)):
            continue
        if current_value < baseline_value - tolerance:
            regressions.append(
                f"{metric}: {current_value:.4f} < baseline {baseline_value:.4f} - tolerance {tolerance:.4f}"
            )
    return regressions


def validate_quality_thresholds(
    report: dict[str, Any], thresholds: dict[str, float]
) -> list[str]:
    """校验发布门槛；未测得的指标会明确报错，防止覆盖率不足时误判通过。"""
    summary = _as_mapping(report.get("summary"))
    failures: list[str] = []
    for metric, minimum in thresholds.items():
        value = summary.get(metric)
        if not isinstance(value, (int, float)):
            failures.append(f"{metric}: not measured")
        elif value < minimum:
            failures.append(f"{metric}: {value:.4f} < required {minimum:.4f}")
    return failures
