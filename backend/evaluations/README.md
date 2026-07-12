# 商品推荐准确率评测

`recommendation_golden_cases.json` 是版本化的业务标准，不是单元测试样例。初始案例根据本地商品快照整理，带有 `needs-review` 标签；在进入发布门槛前，每个案例都必须由产品、运营或客服共同确认客户说法、期望意图、显式约束、是否应转人工，以及可接受或禁止推荐的商品。

评测器不在 CI 中直接请求 LLM。模型输出存在波动并会产生外部调用成本，CI 只评分已导出的结构化结果；需要更新基线时，由负责人执行一次真实链路回放并人工复核结果。

## 商品键

商品答案统一使用 `brand:product_id_ext`，例如 `联邦家私:59`。只用 `product_id_ext` 会在多品牌外部编号重复时产生误判。

## 结果文件格式

结果可以是 JSON 数组、以 `results` 为键的 JSON，或 JSONL。每条结果至少需要 `case_id`、`intent`、`language`。推荐相关案例还应记录结构化 profile、推荐商品键和响应类型：

```json
{
  "case_id": "zh-dining-table-minimalist-teak",
  "intent": "product_recommendation",
  "language": "zh-Hans",
  "profile": {
    "categories": ["dining_table"],
    "spaces": ["dining_room"],
    "styles": ["minimalist"],
    "materials": ["teak"],
    "hard_constraints": ["categories", "styles", "materials"]
  },
  "selected_product_keys": ["联邦家私:59", "联邦家私:60"],
  "response_kind": "product_recommendation",
  "intent_slots": {"is_recommendation_refresh": false}
}
```

仓库中的 `recommendation_result.example.jsonl` 只用于展示字段格式；它只覆盖一个案例，不能作为基线或发布门槛输入。

商品引用案例使用 `target_product_key`；旧结果中的 `selected_product_id_exts` 和 `target_product_id_ext` 仍可读取，但新增评测不应再使用它们。

## 运行评分

从 `backend` 目录运行：

```bash
python -m scripts.evaluate_recommendation_quality \
  --results evaluations/runs/2026-07-12.jsonl \
  --output evaluations/runs/2026-07-12.report.json \
  --min-metric coverage_rate=1 \
  --min-metric intent_accuracy=0.95 \
  --min-metric profile_constraint_recall=0.95
```

首轮运行不应急于设定商品 Top 3 门槛。先让商品负责人逐条确认 `accepted_product_keys`，再保存人工复核后的报告为基线：

```bash
python -m scripts.evaluate_recommendation_quality \
  --results evaluations/runs/candidate.jsonl \
  --baseline evaluations/baselines/recommendation-baseline.json \
  --allowed-regression 0.01
```

当当前报告中任一已测得指标低于基线减去容忍值，或未达到 `--min-metric` 指定门槛时，命令以退出码 `2` 失败，适合在发布前或模型升级前执行。

## 生成真实链路结果

在已连接测试或预发布产品库、且确认允许调用模型后，可以运行当前意图、需求解析、换批和商品选择核心链路：

```bash
python -m scripts.run_recommendation_evaluation \
  --case-id zh-dining-table-minimalist-teak \
  --output evaluations/runs/candidate.jsonl \
  --allow-live-llm
```

脚本会从当前数据库读取商品，并把 `ProductEntry` 转换为与 Telegram 相同的推荐 payload。它不会发送 Telegram 消息，也不会写入会话、推荐历史或产品库；外部副作用仅是允许模型调用和写入指定的结果文件。建议先在预发布数据库运行，抽样人工检查结果后再全量执行。

## 闭环规则

1. 每次线上误推荐、误转人工、语言错配或上下文引用错误，都先脱敏后补成 golden case。
2. 每个案例的商品答案必须由能确认库存和商品属性的人审核，不能由模型反推答案。
3. 模型、提示词、商品分类、召回或记忆逻辑变更前后，都运行同一批案例并比较报告。
4. 只在覆盖率为 `100%` 时讨论准确率；缺失结果不能视为通过。
5. 基线变化必须附带原因，例如商品下架、产品资料修正或业务规则调整。
