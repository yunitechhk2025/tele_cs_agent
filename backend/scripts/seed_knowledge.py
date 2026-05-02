"""Seed knowledge base entries that mirror the recommended directory structure.

Usage (with backend running on host port 8001 by default):

    python backend/scripts/seed_knowledge.py
    python backend/scripts/seed_knowledge.py --base-url http://localhost:8001 --username admin --password change-me-in-production

The script only uses the Python standard library so it can run inside the project's venv
without extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}: {detail}") from e


def login(base_url: str, username: str, password: str) -> str:
    data = post_json(f"{base_url}/api/auth/login", {"username": username, "password": password})
    token = data.get("access_token")
    if not token:
        raise SystemExit(f"Login response missing access_token: {data}")
    return token


ENTRIES: list[dict] = [
    # ---------- faqs / 常见问题 ----------
    {
        "title": "订单状态查询",
        "category": "常见问题/订单",
        "source": "faqs/orders/order-status.md",
        "content": (
            "## 快速回答\n"
            "登录账户 → 我的订单，即可查看订单当前状态。常见状态：待付款、待发货、已发货、已签收、已完成、已取消。\n\n"
            "## 详细说明\n"
            "1. 登录账号后进入「我的订单」页面，按订单号或时间筛选。\n"
            "2. 点击订单可查看付款、发货、物流、签收等节点。\n"
            "3. 如订单状态长时间未更新，可联系客服并提供订单号。\n\n"
            "## 常见变体\n"
            "- 我下单了几天还没发货？\n"
            "- 怎么看自己的订单进展？\n"
            "- 订单卡在「待发货」是什么意思？\n\n"
            "## 相关主题\n"
            "- 发货时效\n"
            "- 物流追踪\n"
        ),
    },
    {
        "title": "发货时效",
        "category": "常见问题/订单",
        "source": "faqs/orders/shipping-times.md",
        "content": (
            "## 快速回答\n"
            "标准订单 1-3 个工作日内发货，节假日及大促期间可能延长至 5 个工作日。\n\n"
            "## 详细说明\n"
            "1. 现货订单：付款后 1-3 个工作日内出库。\n"
            "2. 定制订单：按生产排期，常见 7-15 个工作日。\n"
            "3. 节假日（春节、十一、双 11 等）顺延，具体以下单页提示为准。\n"
            "4. 若超过承诺时效仍未发货，可申请催单或退款。\n\n"
            "## 常见变体\n"
            "- 多久能发货？\n"
            "- 大促期间会延迟吗？\n"
            "- 是否支持加急？\n\n"
            "## 相关主题\n"
            "- 订单状态查询\n"
            "- 物流追踪\n"
        ),
    },
    {
        "title": "物流追踪",
        "category": "常见问题/订单",
        "source": "faqs/orders/tracking-info.md",
        "content": (
            "## 快速回答\n"
            "订单发货后会在「我的订单」生成运单号，点击运单号可跳转物流公司官网查看实时轨迹。\n\n"
            "## 详细说明\n"
            "1. 发货后 24 小时内，物流轨迹可能尚未上传，属于正常情况。\n"
            "2. 海外订单可使用 17track 等聚合查询站，输入运单号查询。\n"
            "3. 若 5 个自然日仍无任何物流更新，请联系客服核实。\n\n"
            "## 常见变体\n"
            "- 我的快递怎么查？\n"
            "- 运单号在哪里看？\n"
            "- 物流没更新怎么办？\n\n"
            "## 相关主题\n"
            "- 订单状态查询\n"
            "- 退换货流程\n"
        ),
    },
    {
        "title": "退货政策概要",
        "category": "常见问题/退货",
        "source": "faqs/returns/return-policy.md",
        "content": (
            "## 快速回答\n"
            "未拆封商品支持自签收日起 7 天无理由退货，已拆封但未影响二次销售可在 15 天内协商退货。\n\n"
            "## 详细说明\n"
            "1. 7 天无理由：保持包装完整、配件齐全、未使用。\n"
            "2. 质量问题：自签收 30 天内可申请退货退款，运费由我方承担。\n"
            "3. 定制商品：原则上不支持无理由退货，质量问题除外。\n\n"
            "## 常见变体\n"
            "- 可以退货吗？\n"
            "- 几天内可以退？\n"
            "- 拆开包装还能退吗？\n\n"
            "## 相关主题\n"
            "- 退款时间线\n"
            "- 换货流程\n"
            "- 完整退货政策\n"
        ),
    },
    {
        "title": "退款时间线",
        "category": "常见问题/退货",
        "source": "faqs/returns/refund-timeline.md",
        "content": (
            "## 快速回答\n"
            "审核通过后，1-3 个工作日内发起退款，到账时间取决于支付渠道（银行卡 1-7 天，信用卡 3-10 天）。\n\n"
            "## 详细说明\n"
            "1. 仓库验收商品 → 财务审核 → 原路退款。\n"
            "2. 退款会原路返回到下单时使用的支付方式。\n"
            "3. 跨境订单含税费，部分税费由清关方处理，请保留申报凭证。\n\n"
            "## 常见变体\n"
            "- 多久能退到账？\n"
            "- 钱什么时候退？\n"
            "- 退款会到原卡吗？\n\n"
            "## 相关主题\n"
            "- 退货政策概要\n"
            "- 完整退货政策\n"
        ),
    },
    {
        "title": "换货流程",
        "category": "常见问题/退货",
        "source": "faqs/returns/exchange-process.md",
        "content": (
            "## 快速回答\n"
            "在「我的订单」选择对应商品 → 申请换货 → 填写问题描述并上传图片 → 客服审核 → 寄回旧品 → 仓库验收后寄出新品。\n\n"
            "## 详细说明\n"
            "1. 换货优先寄出新品，旧品需在 7 天内寄回，否则订单可能被关闭并扣款。\n"
            "2. 颜色/尺寸不符等非质量问题需买家承担来回运费。\n"
            "3. 全球订单换货按不同区域运费策略执行，详询客服。\n\n"
            "## 常见变体\n"
            "- 我想换一个颜色\n"
            "- 尺码不合适怎么换？\n"
            "- 换货怎么操作？\n\n"
            "## 相关主题\n"
            "- 退货政策概要\n"
            "- 退款时间线\n"
        ),
    },
    {
        "title": "产品规格说明",
        "category": "常见问题/产品",
        "source": "faqs/products/product-specs.md",
        "content": (
            "## 快速回答\n"
            "在商品详情页向下滚动至「规格参数」区域，可查看材质、尺寸、重量、颜色、配件清单等。\n\n"
            "## 详细说明\n"
            "1. 材质：以图文卡片形式展示主结构、面料/皮革、海绵密度等。\n"
            "2. 尺寸：长 × 宽 × 高（单位 cm），含外箱尺寸方便估算运输。\n"
            "3. 配件：标配清单与可选选配件均会列出。\n"
            "4. 公差：手工/拼接产品存在 ±2cm 内的公差，属正常范围。\n\n"
            "## 常见变体\n"
            "- 这个沙发多重？\n"
            "- 用的是什么皮？\n"
            "- 标配有几个抱枕？\n\n"
            "## 相关主题\n"
            "- 故障排查\n"
            "- 保修条款\n"
        ),
    },
    {
        "title": "故障排查",
        "category": "常见问题/产品",
        "source": "faqs/products/troubleshooting.md",
        "content": (
            "## 快速回答\n"
            "请先按商品说明书自检；常见问题如异响、晃动、电动功能不动作等大多可通过紧固或重置解决。\n\n"
            "## 详细说明\n"
            "1. 异响：检查地面是否平整，可在底脚加垫片；木质连接处可补涂润滑蜡。\n"
            "2. 晃动：检查所有螺丝是否拧紧，建议两人协作复紧。\n"
            "3. 电动功能：确认电源、保险丝、遥控器电池；尝试断电 30 秒再上电重置。\n"
            "4. 仍无法解决：拍摄 30 秒视频 + 订单号，联系客服开启售后流程。\n\n"
            "## 常见变体\n"
            "- 沙发吱吱响怎么办？\n"
            "- 电动按钮没反应？\n"
            "- 抽屉滑轨卡住？\n\n"
            "## 相关主题\n"
            "- 保修条款\n"
            "- 升级转人工指南\n"
        ),
    },
    # ---------- policies / 政策文档 ----------
    {
        "title": "完整退货政策",
        "category": "政策文档/退货政策",
        "source": "policies/return-policy-full.md",
        "content": (
            "## 适用范围\n"
            "本政策适用于通过本平台官方渠道购买的全部商品，定制类、清仓类商品另有说明者从其约定。\n\n"
            "## 退货条件\n"
            "1. 7 天无理由：未拆封、配件齐全、未使用、不影响二次销售。\n"
            "2. 质量问题：30 天内可申请退货退款，由本方承担来回运费。\n"
            "3. 不支持退货：定制商品、清仓促销特别标注「不支持退货」的商品。\n\n"
            "## 退货流程\n"
            "1. 在线发起申请并上传问题图片/视频。\n"
            "2. 客服 1 个工作日内审核回复。\n"
            "3. 审核通过后 7 天内寄回，逾期视为放弃。\n"
            "4. 仓库验收无误后 1-3 个工作日内发起退款。\n\n"
            "## 退款规则\n"
            "原路退回到下单支付方式；跨境订单的关税/清关费按目的国规定执行。\n\n"
            "## 联系方式\n"
            "如有疑问请联系客服，工作时间：周一至周六 9:00-21:00 (UTC+8)。\n"
        ),
    },
    {
        "title": "保修条款",
        "category": "政策文档/保修条款",
        "source": "policies/warranty-terms.md",
        "content": (
            "## 保修期\n"
            "1. 主体结构：3 年（自签收日起算）。\n"
            "2. 电动机芯/电池/控制器：1 年。\n"
            "3. 易损件（皮料磨损、面料起球、海绵塌陷）：6 个月。\n\n"
            "## 保修范围\n"
            "正常家庭使用条件下出现的非人为故障；商用、出租等场景不在保修范围内。\n\n"
            "## 不在保修范围\n"
            "- 因不当使用、自行拆装造成的损坏\n"
            "- 自然灾害、外力撞击\n"
            "- 未按说明书清洁导致的褪色或腐蚀\n\n"
            "## 售后处理\n"
            "1. 提交故障描述 + 视频 + 订单号。\n"
            "2. 工程师远程指导排查。\n"
            "3. 必要时寄送配件或上门服务（仅大陆地区，海外按当地服务网点）。\n"
        ),
    },
    {
        "title": "隐私政策",
        "category": "政策文档/隐私政策",
        "source": "policies/privacy-policy.md",
        "content": (
            "## 我们收集的信息\n"
            "- 账号信息：姓名、电话、邮箱、收货地址。\n"
            "- 交易信息：订单、支付凭证（不存储完整卡号）。\n"
            "- 设备信息：IP、设备型号、操作系统，用于安全风控。\n\n"
            "## 信息使用目的\n"
            "1. 完成订单交付与售后。\n"
            "2. 改进产品体验与个性化推荐。\n"
            "3. 法律法规要求的合规审计。\n\n"
            "## 第三方共享\n"
            "仅在以下场景与必要的第三方共享：物流公司、支付机构、监管机构。所有第三方均签订数据处理协议。\n\n"
            "## 用户权利\n"
            "您可随时申请查询、更正、删除个人数据。如需注销账号请联系客服。\n\n"
            "## 联系我们\n"
            "数据保护负责人邮箱：dpo@example.com\n"
        ),
    },
    # ---------- procedures / 操作流程 ----------
    {
        "title": "升级转人工指南",
        "category": "操作流程",
        "source": "procedures/escalation-guide.md",
        "content": (
            "## 何时转人工\n"
            "1. 客户明确要求人工或多次表达不满情绪。\n"
            "2. 涉及金额较大的退款、争议、法律相关咨询。\n"
            "3. AI 三轮内无法识别意图，或客户重复同一问题。\n"
            "4. 涉及合同/合作/B 端询价类咨询。\n\n"
            "## 转人工前的准备\n"
            "- 自动汇总：客户语言、订单号、上下文摘要。\n"
            "- 标注：紧急程度（低/中/高）、问题分类。\n\n"
            "## 转交话术（多语言）\n"
            "- 中文：稍等，正在为您接入人工客服。\n"
            "- English: One moment, transferring you to a human agent.\n"
            "- 日本語: 担当者におつなぎします、少々お待ちください。\n\n"
            "## 转人工后\n"
            "1. 人工 30 秒内首次回复。\n"
            "2. 若 5 分钟无人响应，系统自动通知主管。\n"
            "3. 关闭会话前必须有结案备注。\n"
        ),
    },
    {
        "title": "常见问题处置 SOP",
        "category": "操作流程",
        "source": "procedures/common-resolutions.md",
        "content": (
            "## 投诉发货延迟\n"
            "1. 安抚 + 道歉。\n"
            "2. 查询仓储/物流系统给出确切预计时间。\n"
            "3. 若延误 > 5 个工作日：补偿优惠券或现金红包。\n\n"
            "## 投诉商品质量\n"
            "1. 请客户提供视频/图片。\n"
            "2. 走质保流程，必要时寄送备件或换货。\n"
            "3. 高金额（≥ ¥3000）需主管审批。\n\n"
            "## 客户语气激动\n"
            "1. 倾听、复述、共情。\n"
            "2. 不与客户辩论事实，先解决情绪。\n"
            "3. 明确给出下一步与时间承诺，并主动跟进到结果。\n\n"
            "## 跨境订单关税争议\n"
            "1. 引导客户保留清关单据。\n"
            "2. 明示运费/关税分担规则（参见完整退货政策）。\n"
            "3. 若属操作失误，按金额走专项补偿审批。\n"
        ),
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("KB_BASE_URL", "http://localhost:8001"))
    parser.add_argument("--username", default=os.environ.get("KB_USERNAME", "admin"))
    parser.add_argument(
        "--password",
        default=os.environ.get("KB_PASSWORD", "change-me-in-production"),
    )
    args = parser.parse_args()

    print(f"[seed] logging in to {args.base_url} as {args.username}")
    token = login(args.base_url, args.username, args.password)
    print("[seed] login ok")

    created = 0
    for idx, entry in enumerate(ENTRIES, 1):
        print(f"[seed] ({idx}/{len(ENTRIES)}) {entry['category']} :: {entry['title']}")
        try:
            post_json(f"{args.base_url}/api/knowledge", entry, token=token)
            created += 1
        except SystemExit as exc:
            print(f"  ! failed: {exc}", file=sys.stderr)
    print(f"[seed] done; created {created}/{len(ENTRIES)} entries")


if __name__ == "__main__":
    main()
