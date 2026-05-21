# 左右家居家具数据

- 抓取日期：`2026-04-08`
- 来源官网：[https://www.zuoyou-sofa.com/goods.html](https://www.zuoyou-sofa.com/goods.html)
- 抓取方式：调用官网内容接口 `/api/v1/channels/317` 枚举产品树，再按叶子频道调用 `/api/v1/contents` 与 `/api/v1/contents/317/{channelId}/{id}` 抓取详情。
- 当前数据量：`102` 行

## 文件说明

- `zuoyou_sofa_furniture.csv`：左右家居官网产品库中可见的家具/家居产品明细。

## 字段说明

- `crawl_date`：本次整理日期。
- `brand`：品牌名称，固定为“左右家居”。
- `top_brand`：产品库一级品牌，如左右品牌、维特利、造境、左右严选等。
- `subbrand`：二级子品牌；如该产品直接挂在一级品牌下则为空。
- `series_name`：红框对应的产品系列；若该产品无显式系列则为空。
- `channel_path_names` / `channel_path_ids`：该商品在产品库中的频道路径名称与 ID 路径。
- `channel_id`：当前商品所属的叶子频道 ID。
- `product_id`：官网商品内容 ID。
- `product_title`：官网详情页标题原文。
- `product_code`：型号/编号，优先取详情字段，其次从标题中提取。
- `product_name_inferred`：去除品牌前缀和型号后，推断出的商品名称。
- `category_inferred`：按标题、系列、子品牌、规格、描述等信息推断的品类，如沙发类、床类、桌类、椅类、柜类等。
- `category_inference_basis`：本次品类补全的依据。
- `style` / `color` / `fabric` / `detailed_fabric`：风格、颜色、面料及细分面料。
- `specifications`：规格/尺寸。
- `specific_material`：材质说明。
- `description_text`：产品描述。
- `design_highlights`：设计亮点/设计说明。
- `primary_image_url`：主图 URL。
- `gallery_image_count` / `gallery_image_urls`：图集数量及全部图片 URL（`|` 分隔）。
- `display_image_count` / `display_image_urls`：判定为“展示图”的数量与原始 URL。
- `display_image_local_paths`：展示图下载到本地后的相对路径。
- `display_image_selection_basis`：展示图筛选依据。
- `detail_url`：官网商品详情页链接。
- `source_page_url`：本批数据来源页。
- `source_api_list_channel_ids`：抓取该记录时使用的列表接口频道 ID。

## 备注

- 已按你的要求排除“左右家居 高端定制”整条分支，不纳入本表。
- `category_inferred` 为基于现有文本字段做的规则推断；若官网未直接标注且文案线索不足，可能会保留为“未识别”。

## 展示图抓取逻辑

- 这里的“产品图”定义为前端详情页图集，不包含介绍区的说明性长图。
- 优先读取详情接口中的 `imageUrl` 以及 `imageUrl1..n` 字段，这些字段本身就是官网商品图集。
- 由于左右家居的图片语义已经在接口层显式给出，所以不需要额外依赖截图识别或背景识别来判断“展示图”。
- 若图集字段为空，则回退到主图，保证该商品仍有至少一张可用展示图。
- 最终会对 URL 去重、保持原始顺序，并把结果写入 `display_image_*` 字段，同时下载到 `data/images/zuoyou/{product_id}/`。
