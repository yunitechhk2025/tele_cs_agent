import unittest
from datetime import datetime, timedelta

from app.services.observability_service import (
    DEFAULT_ALERT_SETTINGS,
    build_observability_export_zip,
    build_observability_stage_trends,
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

    def test_summary_uses_current_chinese_stage_labels_for_historical_rows(self):
        summary = build_observability_summary(
            [],
            [
                {
                    "stage_key": "parsing_product_profile",
                    "stage_label": "parsing_product_profile",
                    "duration_ms": 300,
                    "success": True,
                    "metadata_json": "{}",
                },
                {
                    "stage_key": "classifying_intent",
                    "stage_label": "classifying_intent",
                    "duration_ms": 200,
                    "success": True,
                    "metadata_json": "{}",
                },
            ],
            [],
            [],
        )

        labels = {item["stage_key"]: item["stage_label"] for item in summary["stage_metrics"]}

        self.assertEqual(labels["parsing_product_profile"], "解析商品需求中")
        self.assertEqual(labels["classifying_intent"], "识别客户意图中")

    def test_stage_trends_group_by_intent_stage_and_hour_bucket(self):
        start = datetime(2026, 5, 28, 10, 0, 0)
        steps = [
            {
                "stage_key": "product_matching",
                "stage_label": "product_matching",
                "primary_intent": "product_recommendation",
                "duration_ms": 100,
                "success": True,
                "started_at": start + timedelta(minutes=5),
            },
            {
                "stage_key": "product_matching",
                "stage_label": "product_matching",
                "primary_intent": "product_recommendation",
                "duration_ms": 300,
                "success": True,
                "started_at": start + timedelta(minutes=35),
            },
            {
                "stage_key": "knowledge_retrieval",
                "stage_label": "knowledge_retrieval",
                "primary_intent": "general_question",
                "duration_ms": 80,
                "success": True,
                "started_at": start + timedelta(hours=1, minutes=2),
            },
        ]

        trends = build_observability_stage_trends(
            steps,
            range_key="24h",
            window_start=start,
            window_end=start + timedelta(hours=2),
        )

        self.assertEqual(trends["granularity"], "hour")
        intent_groups = {group["intent"]: group for group in trends["intents"]}
        product_group = intent_groups["product_recommendation"]
        self.assertEqual(product_group["intent_label"], "商品推荐")
        product_stage = product_group["stages"][0]
        self.assertEqual(product_stage["stage_label"], "匹配推荐商品中")
        self.assertEqual(product_stage["points"][0]["bucket_label"], "05-28 10:00")
        self.assertEqual(product_stage["points"][0]["avg_ms"], 200)
        self.assertEqual(product_stage["points"][0]["p95_ms"], 300)

    def test_alert_candidates_include_representative_conversation_samples(self):
        now = datetime.utcnow()
        summary = {
            "kpis": {
                "text_first_response_p95_ms": 1000,
                "product_recommendation_first_response_p95_ms": 1000,
                "scene_failure_rate": 0.0,
                "llm_failure_rate": 0.2,
                "failure_rate": 0.2,
                "rag_empty_rate": 0.0,
                "profile_handoff_rate": 0.2,
            },
            "alert_samples": {
                "turn_failure_rate": [11, 12],
                "llm_failure_rate": [21],
                "profile_handoff_rate": [31, 32, 33],
            },
        }
        settings = dict(DEFAULT_ALERT_SETTINGS)

        alerts = evaluate_alert_candidates(
            summary,
            settings,
            window_start=now - timedelta(minutes=15),
            window_end=now,
            scope_key="all",
        )
        by_key = {alert["metric_key"]: alert for alert in alerts}

        self.assertEqual(by_key["turn_failure_rate"]["sample_conversation_ids_json"], "[11, 12]")
        self.assertEqual(by_key["turn_failure_rate"]["sample_count"], 2)
        self.assertEqual(by_key["profile_handoff_rate"]["sample_count"], 3)
        self.assertEqual(by_key["llm_failure_rate"]["sample_conversation_ids_json"], "[21]")

    def test_export_zip_contains_observability_csv_reports(self):
        now = datetime(2026, 5, 28, 10, 0, 0)
        summary = {
            "kpis": {"total_turns": 2, "success_rate": 0.5},
            "stage_metrics": [
                {
                    "stage_key": "product_matching",
                    "stage_label": "匹配推荐商品中",
                    "count": 2,
                    "avg_ms": 100,
                    "p50_ms": 100,
                    "p95_ms": 200,
                    "p99_ms": 200,
                    "failed_count": 0,
                }
            ],
            "llm_metrics": [],
            "recent_failures": [
                {
                    "source": "turn",
                    "conversation_id": 11,
                    "turn_metric_id": 2,
                    "language": "zh-Hans",
                    "primary_intent": "product_recommendation",
                    "response_kind": "profile_handoff",
                    "error_message": "handoff",
                    "created_at": now,
                }
            ],
        }
        alerts = [
            {
                "id": 1,
                "severity": "warning",
                "metric_key": "turn_failure_rate",
                "title": "失败率过高",
                "message": "失败率超过阈值",
                "observed_value": 0.5,
                "threshold_value": 0.05,
                "status": "open",
                "sample_conversation_ids_json": "[11]",
                "sample_count": 1,
                "window_start": now - timedelta(minutes=15),
                "window_end": now,
                "created_at": now,
            }
        ]

        zip_bytes = build_observability_export_zip(summary, alerts)

        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            self.assertEqual(
                sorted(zf.namelist()),
                [
                    "alerts.csv",
                    "kpis.csv",
                    "llm_metrics.csv",
                    "recent_failures.csv",
                    "stage_metrics.csv",
                ],
            )
            self.assertIn("total_turns,2", zf.read("kpis.csv").decode("utf-8-sig"))
            self.assertIn("匹配推荐商品中", zf.read("stage_metrics.csv").decode("utf-8-sig"))
            self.assertIn("[11]", zf.read("alerts.csv").decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
