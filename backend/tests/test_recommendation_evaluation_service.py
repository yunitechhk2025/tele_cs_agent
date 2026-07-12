import json
import tempfile
import unittest
from pathlib import Path

from app.services.recommendation_evaluation_service import (
    compare_report_to_baseline,
    evaluate_recommendation_quality,
    load_recommendation_evaluation_cases,
    load_recommendation_evaluation_results,
    validate_quality_thresholds,
)


class RecommendationEvaluationServiceTests(unittest.TestCase):
    def test_scores_intent_profile_product_and_refresh_checks(self):
        cases = [
            {
                "case_id": "desk-refresh",
                "input": {"message": "show me other desks", "language": "en"},
                "expected": {
                    "intent": "product_recommendation",
                    "profile": {
                        "categories": ["desk"],
                        "spaces": ["study"],
                        "hard_constraints": ["categories", "spaces"],
                    },
                    "accepted_product_keys": ["brand-a:desk-02", "brand-a:desk-03"],
                    "forbidden_product_keys": ["brand-a:desk-01"],
                    "should_handoff": False,
                    "is_recommendation_refresh": True,
                },
            }
        ]
        results = {
            "desk-refresh": {
                "case_id": "desk-refresh",
                "intent": "product_recommendation",
                "language": "en",
                "profile": {
                    "categories": ["desk"],
                    "spaces": ["study"],
                    "hard_constraints": ["categories", "spaces"],
                },
                "selected_product_keys": ["brand-a:desk-03"],
                "response_kind": "product_recommendation",
                "intent_slots": {"is_recommendation_refresh": True},
            }
        }

        report = evaluate_recommendation_quality(cases, results)

        self.assertEqual(report["summary"]["coverage_rate"], 1.0)
        self.assertEqual(report["summary"]["intent_accuracy"], 1.0)
        self.assertEqual(report["summary"]["profile_constraint_recall"], 1.0)
        self.assertEqual(report["summary"]["product_top3_hit_rate"], 1.0)
        self.assertEqual(report["summary"]["refresh_semantics_accuracy"], 1.0)
        self.assertEqual(report["summary"]["case_pass_rate"], 1.0)

    def test_reports_missing_result_and_forbidden_product_violation(self):
        cases = [
            {
                "case_id": "missing",
                "input": {"message": "recommend a sofa", "language": "en"},
                "expected": {"intent": "product_recommendation"},
            },
            {
                "case_id": "forbidden",
                "input": {"message": "recommend a desk", "language": "en"},
                "expected": {
                    "intent": "product_recommendation",
                    "forbidden_product_keys": ["brand-a:chair-01"],
                },
            },
        ]
        results = {
            "forbidden": {
                "case_id": "forbidden",
                "intent": "product_recommendation",
                "language": "en",
                "selected_product_keys": ["brand-a:chair-01"],
                "response_kind": "product_recommendation",
            }
        }

        report = evaluate_recommendation_quality(cases, results)

        self.assertEqual(report["summary"]["coverage_rate"], 0.5)
        self.assertEqual(report["summary"]["forbidden_product_violation_rate"], 1.0)
        self.assertEqual(report["summary"]["case_pass_rate"], 0.0)
        self.assertEqual(report["cases"][0]["status"], "missing_result")
        self.assertIn("forbidden_product_ids", report["cases"][1]["failed_checks"])

    def test_loaders_accept_json_and_jsonl_and_validate_duplicate_case_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases_path = root / "cases.json"
            results_path = root / "results.jsonl"
            cases_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "cases": [
                            {
                                "case_id": "case-1",
                                "input": {"message": "desk", "language": "en"},
                                "expected": {"intent": "product_recommendation"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            results_path.write_text(
                '{"case_id":"case-1","intent":"product_recommendation"}\n',
                encoding="utf-8",
            )

            cases = load_recommendation_evaluation_cases(cases_path)
            results = load_recommendation_evaluation_results(results_path)

        self.assertEqual(cases[0]["case_id"], "case-1")
        self.assertEqual(results["case-1"]["intent"], "product_recommendation")

    def test_baseline_comparison_only_flags_measured_metric_regressions(self):
        report = {
            "summary": {
                "intent_accuracy": 0.90,
                "product_top3_hit_rate": None,
                "case_pass_rate": 0.80,
            }
        }
        baseline = {
            "summary": {
                "intent_accuracy": 0.95,
                "product_top3_hit_rate": 0.80,
                "case_pass_rate": 0.80,
            }
        }

        regressions = compare_report_to_baseline(report, baseline, allowed_regression=0.02)

        self.assertEqual(regressions, ["intent_accuracy: 0.9000 < baseline 0.9500 - tolerance 0.0200"])

    def test_thresholds_reject_missing_or_too_low_metrics(self):
        report = {"summary": {"coverage_rate": 1.0, "intent_accuracy": None}}

        failures = validate_quality_thresholds(
            report,
            {"coverage_rate": 1.0, "intent_accuracy": 0.95},
        )

        self.assertEqual(failures, ["intent_accuracy: not measured"])


if __name__ == "__main__":
    unittest.main()
