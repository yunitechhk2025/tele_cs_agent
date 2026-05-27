import unittest
from datetime import datetime, timedelta

from app.services.observability_service import (
    DEFAULT_ALERT_SETTINGS,
    build_observability_summary,
    evaluate_alert_candidates,
    percentile,
)


class ObservabilityServiceTests(unittest.TestCase):
    def test_empty_summary_returns_zero_values(self):
        summary = build_observability_summary([], [], [], [])

        self.assertEqual(summary["kpis"]["total_turns"], 0)
        self.assertEqual(summary["kpis"]["success_rate"], 0)
        self.assertEqual(summary["stage_metrics"], [])
        self.assertEqual(summary["llm_metrics"], [])
        self.assertEqual(summary["recent_failures"], [])

    def test_percentile_uses_nearest_rank(self):
        values = [1000, 2000, 3000, 4000]

        self.assertEqual(percentile(values, 50), 2000)
        self.assertEqual(percentile(values, 95), 4000)
        self.assertIsNone(percentile([], 95))

    def test_summary_aggregates_turn_stage_rag_llm_and_scene_metrics(self):
        now = datetime.utcnow()
        turns = [
            {
                "id": 1,
                "conversation_id": 10,
                "bot_id": 1,
                "language": "zh-Hans",
                "primary_intent": "general_question",
                "response_kind": "text",
                "first_response_ms": 1000,
                "total_ms": 1800,
                "success": True,
                "error_message": "",
                "started_at": now,
            },
            {
                "id": 2,
                "conversation_id": 11,
                "bot_id": 1,
                "language": "zh-Hans",
                "primary_intent": "product_recommendation",
                "response_kind": "profile_handoff",
                "first_response_ms": 9000,
                "total_ms": 9500,
                "success": False,
                "error_message": "handoff",
                "started_at": now + timedelta(seconds=1),
            },
        ]
        steps = [
            {
                "stage_key": "knowledge_retrieval",
                "stage_label": "Knowledge",
                "duration_ms": 120,
                "success": True,
                "metadata_json": '{"retrieved_chars": 0}',
            },
            {
                "stage_key": "knowledge_retrieval",
                "stage_label": "Knowledge",
                "duration_ms": 80,
                "success": True,
                "metadata_json": '{"retrieved_chars": 340}',
            },
            {
                "stage_key": "product_matching",
                "stage_label": "Product matching",
                "duration_ms": 620,
                "success": False,
                "metadata_json": '{"selected_product_count": 0}',
            },
        ]
        llm_calls = [
            {
                "operation": "general_response",
                "model": "qwen",
                "duration_ms": 600,
                "success": True,
                "error_message": "",
            },
            {
                "operation": "general_response",
                "model": "qwen",
                "duration_ms": 1200,
                "success": False,
                "error_message": "timeout",
            },
        ]
        scenes = [
            {"status": "completed", "duration_ms": 5000, "error_message": ""},
            {"status": "failed", "duration_ms": 7000, "error_message": "bad image"},
        ]

        summary = build_observability_summary(turns, steps, llm_calls, scenes)

        kpis = summary["kpis"]
        self.assertEqual(kpis["total_turns"], 2)
        self.assertEqual(kpis["success_rate"], 0.5)
        self.assertEqual(kpis["failure_rate"], 0.5)
        self.assertEqual(kpis["first_response_p50_ms"], 1000)
        self.assertEqual(kpis["first_response_p95_ms"], 9000)
        self.assertEqual(kpis["handoff_rate"], 0.5)
        self.assertEqual(kpis["profile_handoff_rate"], 0.5)
        self.assertEqual(kpis["rag_empty_rate"], 0.5)
        self.assertEqual(kpis["llm_failure_rate"], 0.5)
        self.assertEqual(kpis["scene_failure_rate"], 0.5)

        stage_metrics = {item["stage_key"]: item for item in summary["stage_metrics"]}
        self.assertEqual(stage_metrics["knowledge_retrieval"]["count"], 2)
        self.assertEqual(stage_metrics["knowledge_retrieval"]["avg_ms"], 100)
        self.assertEqual(stage_metrics["product_matching"]["failed_count"], 1)

        llm_metric = summary["llm_metrics"][0]
        self.assertEqual(llm_metric["operation"], "general_response")
        self.assertEqual(llm_metric["count"], 2)
        self.assertEqual(llm_metric["failure_rate"], 0.5)
        self.assertEqual(llm_metric["last_error"], "timeout")

        self.assertEqual(summary["recent_failures"][0]["conversation_id"], 11)

    def test_alert_candidates_are_created_when_thresholds_are_exceeded(self):
        now = datetime.utcnow()
        settings = dict(DEFAULT_ALERT_SETTINGS)
        settings["turn_failure_rate"] = 0.05
        settings["llm_failure_rate"] = 0.1
        summary = {
            "kpis": {
                "text_first_response_p95_ms": 9000,
                "product_recommendation_first_response_p95_ms": 13000,
                "scene_failure_rate": 0.25,
                "llm_failure_rate": 0.2,
                "failure_rate": 0.08,
                "rag_empty_rate": 0.5,
                "profile_handoff_rate": 0.2,
            }
        }

        alerts = evaluate_alert_candidates(
            summary,
            settings,
            window_start=now - timedelta(minutes=15),
            window_end=now,
            scope_key="all",
        )

        keys = {alert["metric_key"] for alert in alerts}
        self.assertIn("text_first_response_p95_ms", keys)
        self.assertIn("product_recommendation_first_response_p95_ms", keys)
        self.assertIn("scene_failure_rate", keys)
        self.assertIn("llm_failure_rate", keys)
        self.assertIn("turn_failure_rate", keys)
        self.assertIn("rag_empty_rate", keys)
        self.assertIn("profile_handoff_rate", keys)
        self.assertTrue(all(alert["dedupe_key"].endswith(":all") for alert in alerts))


if __name__ == "__main__":
    unittest.main()
