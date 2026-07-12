"""对商品推荐 golden cases 的一次运行结果进行离线评分。

示例：
    python -m scripts.evaluate_recommendation_quality \
        --results evaluations/runs/2026-07-12.jsonl \
        --output evaluations/runs/2026-07-12.report.json \
        --min-metric coverage_rate=1 \
        --min-metric intent_accuracy=0.95

results 文件只保存实际链路产出的结构化字段，不保存客户原始对话或模型原始回复，
便于脱敏后进入版本库或 CI 工件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.recommendation_evaluation_service import (  # noqa: E402
    compare_report_to_baseline,
    evaluate_recommendation_quality,
    load_recommendation_evaluation_cases,
    load_recommendation_evaluation_results,
    validate_quality_thresholds,
)


DEFAULT_CASES_PATH = PROJECT_ROOT / "evaluations" / "recommendation_golden_cases.json"


def _parse_metric_threshold(raw: str) -> tuple[str, float]:
    """解析 metric=value 参数，避免 CI 配置中出现无效门槛。"""
    metric, separator, value = raw.partition("=")
    if not separator or not metric.strip():
        raise argparse.ArgumentTypeError("threshold must use metric=value")
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold value must be numeric") from exc
    if not 0 <= threshold <= 1:
        raise argparse.ArgumentTypeError("threshold value must be between 0 and 1")
    return metric.strip(), threshold


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score recommendation golden cases")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allowed-regression", type=float, default=0.0)
    parser.add_argument(
        "--min-metric",
        action="append",
        default=[],
        type=_parse_metric_threshold,
        metavar="METRIC=VALUE",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = load_recommendation_evaluation_cases(args.cases)
    results = load_recommendation_evaluation_results(args.results)
    report = evaluate_recommendation_quality(cases, results)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    failures: list[str] = []
    if args.baseline:
        baseline = _read_json(args.baseline)
        failures.extend(
            compare_report_to_baseline(
                report,
                baseline,
                allowed_regression=args.allowed_regression,
            )
        )
    thresholds = dict(args.min_metric)
    failures.extend(validate_quality_thresholds(report, thresholds))
    if failures:
        for failure in failures:
            print(f"QUALITY_GATE_FAILED: {failure}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
