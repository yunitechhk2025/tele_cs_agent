# 红苹果家具数据

- 抓取日期：`2026-04-08`
- 来源官网：[http://www.redapple.com.cn/product/index.aspx](http://www.redapple.com.cn/product/index.aspx)
- 抓取方式：从 6 个空间大类页抓取系列页，再从系列页抓取具体商品详情页。
- 数据量：`117` 行

## 文件说明

- `redapple_furniture.csv`：红苹果官网中可见家具/家居产品明细。

## 字段说明

- `crawl_date`：本次抓取日期。
- `brand`：品牌名称，固定为“红苹果”。
- `major_category`：官网一级大类，如卧室、书房、客厅、餐厅、床垫、床品。
- `product_id`：从详情页 URL 提取的商品 ID。
- `major_category_url`：一级大类页面链接。
- `series_name`：系列名称。
- `series_summary`：系列说明文案。
- `series_url`：系列列表页链接。
- `series_cover_image_url`：系列封面图。
- `series_declared_product_count`：系列页上显示的商品数量。
- `product_name`：详情页主商品名。
- `list_title`：系列列表页显示的商品标题。
- `model`：型号。
- `style`：风格。
- `material`：材质。
- `color`：颜色。
- `specification`：规格/尺寸。
- `description_text`：商品简介。
- `list_image_url`：系列列表页首图。
- `hover_image_url`：系列列表页 hover 图。
- `gallery_image_count`：详情页图集张数。
- `gallery_image_urls`：详情页图集 URL，使用 `|` 分隔。
- `display_image_count`：判定为“展示图”的图片数量。
- `display_image_urls`：展示图原始 URL，使用 `|` 分隔。
- `display_image_local_paths`：展示图下载到本地后的相对路径，使用 `|` 分隔。
- `display_image_selection_basis`：展示图筛选依据。
- `detail_url`：商品详情页链接。

## 备注

- 官网个别系列可能显示 `0` 款产品，此类系列不会产生明细行。
- `床垫`、`床品` 被官网放在同一产品体系下，因此也保留在表内，便于你后续自行筛选。

## 展示图抓取逻辑

- 这里的“产品图”定义为前端详情页轮换图，或列表卡片层直接展示给用户的商品图，不包含正文说明性质的长图。
- 优先依据详情页脚本变量 `largimg` 提取图集，这组通常就是详情页首屏的大图展示位。
- 如果某个商品详情页没有返回 `largimg`，就退回到系列列表页的首图与 hover 图。
- 之所以不单靠图片清晰度或背景样式判断，是因为红苹果旧站静态页里，最稳定的语义信号其实是 `largimg` 这个字段本身。
- 最终会对 URL 去重、保持原始顺序，并把结果写入 `display_image_*` 字段，同时下载到 `data/images/redapple/{product_id}/`。
