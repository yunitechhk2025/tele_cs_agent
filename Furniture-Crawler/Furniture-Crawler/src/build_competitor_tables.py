import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from utils.http import fetch, fetch_json_url, post_json_url
from utils.text import clean_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data" / "csv"
# 展示图统一落在 data/images 下，并按站点 + product_id 分目录，
# 这样 CSV 中可以稳定回填本地路径，后续做分析或人工抽检时也更直观。
IMAGE_ROOT = PROJECT_ROOT / "data" / "images"
TODAY = date.today().isoformat()
ZUOYOU_BASE_URL = "https://www.zuoyou-sofa.com"
ZUOYOU_SITE_ID = "317"
ZUOYOU_API_KEY = "3c83b5bb-1686-46ea-9210-194a01ab6f68"
ZUOYOU_GOODS_ROOT_ID = 325
ZUOYOU_EXCLUDED_CHANNEL_IDS = {334}


def format_duration(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def log_progress(site: str, current: int, total: int, started_at: float, extra: str = "") -> None:
    # 统一的终端进度输出。显示进度条、当前完成量和累计耗时，
    # 这样全量抓取时可以直观看到“跑了多少”和“已经花了多久”。
    total = max(total, current, 1)
    percent = current / total * 100
    bar_width = 24
    filled = min(bar_width, int(round(percent / 100 * bar_width)))
    bar = "#" * filled + "-" * (bar_width - filled)
    elapsed = format_duration(time.monotonic() - started_at)
    message = f"[{site}] [{bar}] {current}/{total} ({percent:5.1f}%) elapsed={elapsed}"
    if extra:
        message += f" {extra}"
    end = "\r" if sys.stdout.isatty() and current < total else "\n"
    print(message, end=end, flush=True)


def log_completion(site: str, total_rows: int, started_at: float) -> None:
    duration = format_duration(time.monotonic() - started_at)
    print(f"[{site}] 完成，共 {total_rows} 条，总耗时 {duration}", flush=True)


def parse_cli_args(argv: List[str]) -> Tuple[set[str], Optional[set[str]]]:
    # 支持：
    # python3 src/build_competitor_tables.py landbond --id 91
    # python3 src/build_competitor_tables.py landbond --id=91,92
    # python3 src/build_competitor_tables.py --product-id 91
    selected_sites: set[str] = set()
    product_ids: set[str] = set()
    index = 0
    while index < len(argv):
        arg = argv[index].strip()
        if not arg:
            index += 1
            continue
        if arg in {"--id", "--product-id"}:
            if index + 1 >= len(argv):
                raise SystemExit(f"{arg} 需要提供商品 ID，例如 --id 91")
            product_ids.update(part.strip() for part in argv[index + 1].split(",") if part.strip())
            index += 2
            continue
        if arg.startswith("--id="):
            product_ids.update(part.strip() for part in arg.split("=", 1)[1].split(",") if part.strip())
            index += 1
            continue
        if arg.startswith("--product-id="):
            product_ids.update(part.strip() for part in arg.split("=", 1)[1].split(",") if part.strip())
            index += 1
            continue
        if arg.startswith("--"):
            raise SystemExit(f"不支持的参数：{arg}")
        selected_sites.add(arg.lower())
        index += 1

    if not selected_sites:
        selected_sites = {"landbond", "redapple", "zuoyou"}
    return selected_sites, (product_ids or None)


def ensure_dirs() -> Dict[str, Path]:
    # 同时准备 CSV 输出目录和展示图目录。这里集中创建，避免各站点逻辑里
    # 到处散落 mkdir，也方便后续调整项目结构时只改一处。
    dirs = {
        "csv_root": DATA_ROOT,
        "images_root": IMAGE_ROOT,
        "landbond": DATA_ROOT / "landbond",
        "redapple": DATA_ROOT / "redapple",
        "zuoyou_sofa": DATA_ROOT / "zuoyou",
        "landbond_images": IMAGE_ROOT / "landbond",
        "redapple_images": IMAGE_ROOT / "redapple",
        "zuoyou_images": IMAGE_ROOT / "zuoyou",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: Iterable[str]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def dedupe_urls(urls: Iterable[str]) -> List[str]:
    # 官网图集里经常会混入重复 URL，或者同一张图从不同字段重复返回。
    # 这里保持“首个出现顺序不变”的去重，便于：
    # 1. 保留官网原始展示顺序
    # 2. 避免重复下载
    # 3. 让 CSV 中的图片序列和本地文件序号稳定对应
    seen = set()
    result: List[str] = []
    for url in urls:
        clean_url = clean_text(url)
        if clean_url and clean_url not in seen:
            seen.add(clean_url)
            result.append(clean_url)
    return result


def split_pipe_urls(value: str) -> List[str]:
    # 历史字段里图集 URL 用 "|" 拼接，统一拆回列表后再做去重。
    return dedupe_urls(part.strip() for part in clean_text(value).split("|"))


def is_supported_image_url(url: str) -> bool:
    # 产品图只接受常见图片资源；像 mp4 这类视频资源不应再落入 display_image_* 字段。
    # 若 URL 没有后缀，先放行，交给下载阶段继续处理。
    suffix = Path(urlparse(clean_text(url)).path).suffix.lower()
    if not suffix:
        return True
    return suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def filter_image_urls(urls: Iterable[str]) -> List[str]:
    return [url for url in dedupe_urls(urls) if is_supported_image_url(url)]


def extract_landbond_carousel_urls(html: str, detail_url: str) -> List[str]:
    # 联邦产品图以详情页主轮播为准：解析 data-thumb="#thumb" 这组 carousel-item，
    # 只取首屏产品图，不把正文 content 的详情长图混进来。
    if not html:
        return []
    match = re.search(
        r'<div class="layui-carousel"[^>]*data-thumb=[\'"]#thumb[\'"][^>]*>\s*<div carousel-item>(?P<body>.*?)</div>\s*</div>',
        html,
        re.S,
    )
    if not match:
        return []
    body = match.group("body")
    urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body, re.I)
    return filter_image_urls(urljoin(detail_url, url) for url in urls)


def guess_image_extension(url: str) -> str:
    # 绝大多数站点的图片 URL 都带扩展名；若缺失，则保守回退为 jpg，
    # 这样文件在本地可正常预览，也不会因为未知后缀影响落盘。
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return suffix
    return ".jpg"


def download_image(url: str, path: Path, timeout: int = 120) -> bool:
    # 统一通过 curl 下载，原因是：
    # 1. 对重定向和压缩响应支持稳定
    # 2. 可直接复用已有命令行环境
    # 3. 配合 retry 能更稳地处理官网偶发网络抖动
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--compressed",
            "--retry",
            "5",
            "--retry-delay",
            "1",
            "--retry-all-errors",
            "--max-time",
            str(timeout),
            "-o",
            str(path),
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0 or not path.exists() or path.stat().st_size == 0:
        if path.exists():
            path.unlink()
        return False
    return True


def save_display_images(brand_dir: Path, product_id: str, image_urls: List[str]) -> List[str]:
    # 每个商品一个目录，文件名固定为 display_01 / display_02 ...
    # 这样即使原始 URL 很长或参数很多，本地也保持结构统一。
    saved_paths: List[str] = []
    product_dir = brand_dir / product_id
    product_dir.mkdir(parents=True, exist_ok=True)
    for index, image_url in enumerate(filter_image_urls(image_urls), start=1):
        ext = guess_image_extension(image_url)
        filename = f"display_{index:02d}{ext}"
        file_path = product_dir / filename
        # 已存在且非空时直接复用，避免重复抓取同一商品时重复下载。
        if file_path.exists() and file_path.stat().st_size > 0:
            saved_paths.append(str(file_path.relative_to(PROJECT_ROOT)))
            continue
        if download_image(image_url, file_path):
            saved_paths.append(str(file_path.relative_to(PROJECT_ROOT)))
    return saved_paths


def attach_display_images(
    row: Dict[str, str],
    image_root: Path,
    product_id: str,
    image_urls: List[str],
    selection_basis: str,
) -> None:
    # 这个函数负责把“判定后的展示图结果”一次性写回 CSV 行：
    # - 多少张图
    # - 原始 URL
    # - 本地保存路径
    # - 本次判定依据
    # 这样后续做数据分析时，不需要再去反推图片是怎么选出来的。
    display_urls = filter_image_urls(image_urls)
    saved_paths = save_display_images(image_root, product_id, display_urls) if display_urls else []
    row["display_image_count"] = str(len(display_urls))
    row["display_image_urls"] = " | ".join(display_urls)
    row["display_image_local_paths"] = " | ".join(saved_paths)
    row["display_image_selection_basis"] = selection_basis


def normalize_zuoyou_media_url(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("@/"):
        return urljoin(f"{ZUOYOU_BASE_URL}/", value[2:])
    if value.startswith("/"):
        return urljoin(f"{ZUOYOU_BASE_URL}/", value.lstrip("/"))
    return urljoin(f"{ZUOYOU_BASE_URL}/", value)


def extract_zuoyou_gallery_urls(detail: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen = set()
    keys = ["imageUrl"]
    for index in range(1, 21):
        keys.append(f"imageUrl{index}")
    for key in keys:
        normalized = normalize_zuoyou_media_url(str(detail.get(key, "") or ""))
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def extract_zuoyou_product_code(title: str, explicit_code: str) -> str:
    explicit_code = clean_text(explicit_code)
    if explicit_code:
        return explicit_code
    candidates = re.findall(r"[A-Z][A-Z0-9/-]{2,}", title or "")
    filtered: List[str] = []
    for candidate in candidates:
        if not any(ch.isdigit() for ch in candidate):
            continue
        if candidate not in filtered:
            filtered.append(candidate)
    return " / ".join(filtered)


def infer_zuoyou_product_name(title: str, product_code: str) -> str:
    name = clean_text(title)
    if "丨" in name:
        name = name.split("丨", 1)[1].strip()
    if product_code:
        for part in [segment.strip() for segment in product_code.split("/") if segment.strip()]:
            name = re.sub(rf"\b{re.escape(part)}\b", "", name).strip()
    name = re.sub(r"^[|丨/ -]+", "", name).strip()
    name = re.sub(r"[|丨/ -]+$", "", name).strip()
    return name or clean_text(title)


def infer_zuoyou_category(
    top_brand: str,
    subbrand: str,
    series_name: str,
    product_title: str,
    product_name: str,
    description_text: str,
    design_text: str,
    specifications: str,
    material_text: str,
) -> Tuple[str, str]:
    candidates = [
        ("子品牌", clean_text(subbrand)),
        ("系列", clean_text(series_name)),
        ("产品标题", clean_text(product_title)),
        ("产品名称", clean_text(product_name)),
        ("产品描述", clean_text(description_text)),
        ("设计亮点", clean_text(design_text)),
        ("规格尺寸", clean_text(specifications)),
        ("材质", clean_text(material_text)),
        ("顶级品牌", clean_text(top_brand)),
    ]

    def match(category: str, keywords: List[str]) -> Optional[Tuple[str, str]]:
        for source_label, source_text in candidates:
            if not source_text:
                continue
            for keyword in keywords:
                if keyword and keyword in source_text:
                    return category, f"{source_label}匹配“{keyword}”"
        return None

    rules = [
        ("床头柜", ["床头柜"]),
        ("床垫类", ["床垫", "床褥"]),
        ("床类", ["软床", "大床", "双人床", "单人床", "床屏"]),
        ("沙发类", ["沙发床"]),
        ("沙发类", ["电动躺位", "零靠墙", "休位", "单位（电动）", "单位电动", "单位", "两位", "三A", "三B", "四A", "四B", "转B"]),
        ("桌类", ["餐桌", "茶几", "边几", "圆几", "角几", "书桌", "妆台", "妆桌", "案几"]),
        ("椅类", ["餐椅", "休闲椅", "单椅", "扶手椅", "凳", "脚踏"]),
        ("柜类", ["电视柜", "餐边柜", "玄关柜", "斗柜", "边柜", "酒柜", "书柜", "衣柜", "柜"]),
        ("配套类", ["配套"]),
        ("床类", ["床"]),
        ("沙发类", ["沙发", "转角", "休躺", "三位", "双位", "单人位"]),
        ("桌类", ["桌"]),
        ("椅类", ["椅"]),
    ]
    for category, keywords in rules:
        matched = match(category, keywords)
        if matched:
            return matched

    if clean_text(subbrand) in {"左右幸福床垫", "左右睡眠"}:
        return "睡眠类", f"子品牌“{clean_text(subbrand)}”属于睡眠产品线"
    if clean_text(series_name) in {"沙发", "床", "配套"}:
        mapped = {"沙发": "沙发类", "床": "床类", "配套": "配套类"}[clean_text(series_name)]
        return mapped, f"系列“{clean_text(series_name)}”直接指示品类"
    if "左右沙发" in clean_text(subbrand):
        return "沙发类", "子品牌“左右沙发”直接指示品类"
    return "未识别", "未在标题、系列、子品牌、规格或描述中匹配到稳定品类关键词"


def build_landbond(out_dir: Path, product_ids: Optional[set[str]] = None) -> int:
    started_at = time.monotonic()
    image_dir = IMAGE_ROOT / "landbond"
    first_payload = json.loads(fetch("https://www.landbond.com/goods/lists/0/?serie="))
    first_data = first_payload["data"]["data"]
    last_page = int(first_data["last_page"])
    expected_total = len(product_ids) if product_ids else int(first_data["total"])

    rows: List[Dict[str, str]] = []
    seen_ids = set()

    for page in range(1, last_page + 1):
        payload = json.loads(fetch(f"https://www.landbond.com/goods/lists/0/?page={page}&serie="))
        items = payload["data"]["data"]["data"]
        for item in items:
            goods_id = str(item.get("id", "")).strip()
            if not goods_id:
                continue
            if product_ids and goods_id not in product_ids:
                continue
            if goods_id in seen_ids:
                continue
            seen_ids.add(goods_id)

            banner = item.get("banner") or []
            content_html = str(item.get("content", "") or "")
            detail_url = f"https://www.landbond.com/goods/detail/{goods_id}"
            detail_html = fetch(detail_url)
            # 直接以详情页主轮播 <div carousel-item> 为准，保证抓到的是用户前端真正看到的产品图。
            carousel_urls = extract_landbond_carousel_urls(detail_html, detail_url)
            # API banner 作为兜底。这里要取 pic 而不是 image。
            banner_urls = filter_image_urls(
                urljoin("https:", entry.get("pic", ""))
                for entry in banner
                if isinstance(entry, dict) and entry.get("pic")
            )
            fallback_primary_image = row_primary_image = (
                urljoin("https:", item.get("thumb", "")) if item.get("thumb") else ""
            )
            row = {
                "crawl_date": TODAY,
                "brand": "联邦家私",
                "product_id": goods_id,
                "product_name": clean_text(item.get("goods_name", "")),
                "series_name": clean_text(item.get("serie", "")),
                "space": clean_text(item.get("space", "")),
                "style": clean_text(item.get("style", "")),
                "price_display": clean_text(item.get("price", "")),
                "original_price": str(item.get("original_price", "") or "").strip(),
                "size": clean_text(item.get("size", "")),
                "color": clean_text(item.get("color", "")),
                "material": clean_text(item.get("material", "")),
                "serial_number": clean_text(item.get("serial_number", "")),
                "part_no": clean_text(item.get("part_no", "")),
                "primary_image_url": row_primary_image,
                "gallery_image_count": str(len(banner)),
                "description_text": clean_text(item.get("desc", "")),
                "detail_content_text": clean_text(content_html),
                "buy_url": clean_text(item.get("buy_url", "")),
                "detail_url": detail_url,
                "source_endpoint": f"https://www.landbond.com/goods/lists/0/?page={page}&serie=",
                "created_at": clean_text(item.get("created_at", "")),
                "updated_at": clean_text(item.get("updated_at", "")),
            }
            attach_display_images(
                row=row,
                image_root=image_dir,
                product_id=goods_id,
                # 优先使用前端主轮播；若页面解析失败，则退回 API banner；最后才尝试主图，
                # 同时会自动过滤 mp4 等非图片资源。
                image_urls=carousel_urls or banner_urls or ([fallback_primary_image] if fallback_primary_image else []),
                selection_basis="优先解析详情页 carousel-item 主轮播；若失败则回退 API banner；最后回退商品主图 thumb，并过滤非图片资源",
            )
            rows.append(row)
            log_progress("联邦家私", len(rows), expected_total, started_at, f"product_id={goods_id}")
        if product_ids and len(rows) >= len(product_ids):
            break

    if product_ids and not rows:
        raise RuntimeError(f"联邦家私未抓到指定商品 ID：{', '.join(sorted(product_ids))}")

    rows.sort(key=lambda row: int(row["product_id"]))
    fieldnames = [
        "crawl_date",
        "brand",
        "product_id",
        "product_name",
        "series_name",
        "space",
        "style",
        "price_display",
        "original_price",
        "size",
        "color",
        "material",
        "serial_number",
        "part_no",
        "primary_image_url",
        "gallery_image_count",
        "display_image_count",
        "display_image_urls",
        "display_image_local_paths",
        "display_image_selection_basis",
        "description_text",
        "detail_content_text",
        "buy_url",
        "detail_url",
        "source_endpoint",
        "created_at",
        "updated_at",
    ]
    write_csv(out_dir / "landbond_furniture.csv", rows, fieldnames)

    readme = f"""# 联邦家私家具数据

- 抓取日期：`{TODAY}`
- 来源官网：[https://www.landbond.com/goods/index](https://www.landbond.com/goods/index)
- 抓取方式：调用官网公开商品列表接口 `https://www.landbond.com/goods/lists/0/?page={{n}}&serie=`
- 数据量：`{len(rows)}` 行

## 文件说明

- `landbond_furniture.csv`：联邦家私在官网“我想购买”商品体系下可见的家具商品明细。

## 字段说明

- `crawl_date`：本次抓取日期。
- `brand`：品牌名称，固定为“联邦家私”。
- `product_id`：官网商品 ID。
- `product_name`：商品名称。
- `series_name`：系列名称。
- `space`：空间分类，如客厅、餐厅、卧室等。
- `style`：页面展示的风格。
- `price_display`：页面显示价格或价格区间。
- `original_price`：原价字段，原站接口返回值。
- `size`：尺寸/规格。
- `color`：颜色。
- `material`：材质。
- `serial_number`：型号/编号字段。
- `part_no`：配件/部件编号字段。
- `primary_image_url`：主图 URL。
- `gallery_image_count`：详情轮播图张数。
- `display_image_count`：判定为“展示图”的图片数量。
- `display_image_urls`：展示图原始 URL，使用 `|` 分隔。
- `display_image_local_paths`：展示图下载到本地后的相对路径，使用 `|` 分隔。
- `display_image_selection_basis`：展示图筛选依据。
- `description_text`：简短描述字段。
- `detail_content_text`：详情正文清洗后的文本。
- `buy_url`：跳转商城购买链接。
- `detail_url`：官网详情页链接。
- `source_endpoint`：该行记录对应的接口页。
- `created_at` / `updated_at`：官网接口返回的创建和更新时间。

## 备注

- 本表按官网接口可见商品生成，若官网后续新增或下架商品，数据量会变化。
- `detail_content_text` 来源于图文详情清洗，部分内容可能较长。

## 展示图抓取逻辑

- 这里的“产品图”定义为前端商品详情页顶部主轮播，不包含正文 `content` 区域的详情长图。
- 第一优先级直接解析详情页 `carousel-item` 内的图片，这组就是用户前端看到的轮换图。
- 如果详情页轮播解析失败，再回退到接口 `banner.pic`。
- 若前两者都为空，再尝试 `thumb` 主图；但会过滤掉 `mp4` 等非图片资源，避免把视频误存成 `.jpg`。
- `content` 富文本中的长图继续保留在详情信息里，但不再计入 `display_image_*` 字段。
- 最终会对 URL 去重、保持原始顺序，并把结果写入 `display_image_*` 字段，同时下载到 `data/images/landbond/{{product_id}}/`。
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    log_completion("联邦家私", len(rows), started_at)
    return len(rows)


def parse_redapple_category_page(html: str, major_category: str, category_url: str) -> List[Dict[str, str]]:
    pattern = re.compile(
        r'<a href="(?P<href>/product/[^"]+/index\.aspx)">\s*'
        r"<picture>\s*<img src=\"(?P<img>[^\"]+)\"[^>]*>\s*</picture>\s*"
        r"<h2>(?P<title>.*?)</h2>\s*"
        r"<summary>(?P<summary>.*?)</summary>\s*"
        r"<p>共有 <span>(?P<count>\d+)</span> 款产品</p>",
        re.S,
    )
    rows = []
    for match in pattern.finditer(html):
        rows.append(
            {
                "major_category": major_category,
                "major_category_url": category_url,
                "series_name": clean_text(match.group("title")),
                "series_summary": clean_text(match.group("summary")),
                "series_url": urljoin("http://www.redapple.com.cn", match.group("href")),
                "series_cover_image_url": urljoin("http://www.redapple.com.cn", match.group("img")),
                "series_declared_product_count": match.group("count"),
            }
        )
    if rows:
        return rows

    fallback_pattern = re.compile(
        r'<a[^>]+href="(?P<href>/product/[^"]+/index\.aspx)"[^>]*>(?P<body>.*?)</a>',
        re.S,
    )
    seen_urls = set()
    for match in fallback_pattern.finditer(html):
        series_url = urljoin("http://www.redapple.com.cn", match.group("href"))
        if series_url in seen_urls:
            continue
        seen_urls.add(series_url)
        body = match.group("body")
        images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body, re.I)
        title_match = re.search(r"<h2>(.*?)</h2>", body, re.S)
        summary_match = re.search(r"<summary>(.*?)</summary>", body, re.S)
        count_match = re.search(r"共有\s*<span>\s*(\d+)\s*</span>\s*款产品", body, re.S)
        title = clean_text(title_match.group(1)) if title_match else ""
        if not title:
            title = clean_text(re.sub(r"<[^>]+>", " ", body))
        if not title:
            continue
        rows.append(
            {
                "major_category": major_category,
                "major_category_url": category_url,
                "series_name": title,
                "series_summary": clean_text(summary_match.group(1)) if summary_match else "",
                "series_url": series_url,
                "series_cover_image_url": urljoin("http://www.redapple.com.cn", images[0]) if images else "",
                "series_declared_product_count": count_match.group(1) if count_match else "0",
            }
        )
    return rows


def parse_redapple_series_page(html: str, series_meta: Dict[str, str]) -> List[Dict[str, str]]:
    pattern = re.compile(
        r'<a href="(?P<href>/product/[^"]+?\.aspx)"[^>]*>\s*'
        r"<picture>\s*<img src=\"(?P<img1>[^\"]*)\"[^>]*>\s*"
        r"<img src=\"(?P<img2>[^\"]*)\"[^>]*class=\"hover\"[^>]*>\s*</picture>\s*"
        r"<div>\s*<h2>(?P<title>.*?)</h2>",
        re.S,
    )
    rows = []
    for match in pattern.finditer(html):
        rows.append(
            {
                **series_meta,
                "detail_url": urljoin("http://www.redapple.com.cn", match.group("href")),
                "list_image_url": urljoin("http://www.redapple.com.cn", match.group("img1")) if match.group("img1") else "",
                "hover_image_url": urljoin("http://www.redapple.com.cn", match.group("img2")) if match.group("img2") else "",
                "list_title": clean_text(match.group("title")),
            }
        )
    if rows:
        return rows

    fallback_pattern = re.compile(
        r'<a[^>]+href="(?P<href>/product/[^"]+?/(?P<id>\d+)\.aspx)"[^>]*>(?P<body>.*?)</a>',
        re.S,
    )
    seen_urls = set()
    for match in fallback_pattern.finditer(html):
        detail_url = urljoin("http://www.redapple.com.cn", match.group("href"))
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        body = match.group("body")
        images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body, re.I)
        title = ""
        for title_pattern in [r"<h2>(.*?)</h2>", r"<h3>(.*?)</h3>", r"title=[\"']([^\"']+)[\"']", r"alt=[\"']([^\"']+)[\"']"]:
            title_match = re.search(title_pattern, body, re.S | re.I)
            if title_match:
                title = clean_text(title_match.group(1))
                if title:
                    break
        if not title:
            title = clean_text(re.sub(r"<[^>]+>", " ", body))
        if not title:
            title = match.group("id")
        rows.append(
            {
                **series_meta,
                "detail_url": detail_url,
                "list_image_url": urljoin("http://www.redapple.com.cn", images[0]) if images else "",
                "hover_image_url": urljoin("http://www.redapple.com.cn", images[1]) if len(images) > 1 else "",
                "list_title": title,
            }
        )
    return rows


def parse_redapple_detail_page(html: str) -> Dict[str, str]:
    detail: Dict[str, str] = {}
    title_match = re.search(r"<h1>(.*?)</h1>", html, re.S)
    detail["product_name"] = clean_text(title_match.group(1)) if title_match else ""

    summary_match = re.search(r"<summary>(.*?)</summary>", html, re.S)
    detail["description_text"] = clean_text(summary_match.group(1)) if summary_match else ""

    for label, value in re.findall(r"<aside[^>]*><span>([^<]+)</span>(.*?)</aside>", html, re.S):
        label = clean_text(label).rstrip("：:")
        detail[label] = clean_text(value)

    img_match = re.search(r"var largimg=\('(.+?)'\)\.split\('\|'\);", html, re.S)
    gallery_urls = []
    if img_match:
        # 红苹果详情页会把前端轮换图/大图图集塞进 largimg JS 变量里，
        # 这组图比列表图更接近用户在详情页第一屏看到的产品图。
        for part in img_match.group(1).split("|"):
            image_path = part.split("$$", 1)[0].strip()
            if image_path:
                gallery_urls.append(urljoin("http://www.redapple.com.cn", image_path))
    detail["gallery_image_urls"] = " | ".join(gallery_urls)
    detail["gallery_image_count"] = str(len(gallery_urls))
    return detail


def parse_redapple_direct_products_page(
    html: str,
    major_category: str,
    category_url: str,
) -> List[Dict[str, str]]:
    pattern = re.compile(
        r'<a[^>]+href="(?P<href>/product/[^"]+?/(?P<id>\d+)\.aspx)"[^>]*>(?P<body>.*?)</a>',
        re.S,
    )
    rows: List[Dict[str, str]] = []
    seen_urls = set()
    for match in pattern.finditer(html):
        detail_url = urljoin("http://www.redapple.com.cn", match.group("href"))
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        body = match.group("body")
        images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body, re.I)
        title = ""
        for title_pattern in [r"<h2>(.*?)</h2>", r"<h3>(.*?)</h3>", r"title=[\"']([^\"']+)[\"']", r"alt=[\"']([^\"']+)[\"']"]:
            title_match = re.search(title_pattern, body, re.S | re.I)
            if title_match:
                title = clean_text(title_match.group(1))
                if title:
                    break
        summary_match = re.search(r"<summary>(.*?)</summary>", body, re.S)
        title = title or clean_text(re.sub(r"<[^>]+>", " ", body)) or match.group("id")
        rows.append(
            {
                "major_category": major_category,
                "major_category_url": category_url,
                "series_name": "",
                "series_summary": clean_text(summary_match.group(1)) if summary_match else "",
                "series_url": category_url,
                "series_cover_image_url": urljoin("http://www.redapple.com.cn", images[0]) if images else "",
                "series_declared_product_count": "0",
                "detail_url": detail_url,
                "list_image_url": urljoin("http://www.redapple.com.cn", images[0]) if images else "",
                "hover_image_url": urljoin("http://www.redapple.com.cn", images[1]) if len(images) > 1 else "",
                "list_title": title,
            }
        )
    return rows


def build_redapple(out_dir: Path, product_ids: Optional[set[str]] = None) -> int:
    started_at = time.monotonic()
    image_dir = IMAGE_ROOT / "redapple"
    category_map = {
        "p1": "卧室",
        "p2": "书房",
        "p3": "客厅",
        "p4": "餐厅",
        "p5": "床垫",
        "p6": "床品",
    }

    series_rows: List[Dict[str, str]] = []
    direct_product_rows: List[Dict[str, str]] = []
    for code, major_category in category_map.items():
        category_url = f"http://www.redapple.com.cn/product/{code}/index.aspx"
        html = fetch(category_url)
        if "系统加载中" in html and "<div id=\"app\">" in html:
            raise RuntimeError(
                "红苹果分类页当前返回 SPA 壳页面，旧版静态 HTML 解析逻辑无法稳定枚举商品。"
            )
        series_rows.extend(parse_redapple_category_page(html, major_category, category_url))
        direct_product_rows.extend(parse_redapple_direct_products_page(html, major_category, category_url))

    if not series_rows and not direct_product_rows:
        raise RuntimeError("红苹果系列页未解析到任何记录，已停止写入以避免覆盖现有数据。")

    product_rows: List[Dict[str, str]] = []
    seen_urls = set()
    expected_total = len(product_ids) if product_ids else sum(
        int(row.get("series_declared_product_count") or 0) for row in series_rows
    )
    if expected_total <= 0:
        expected_total = len(series_rows) + len(direct_product_rows)
    for series_meta in series_rows:
        html = fetch(series_meta["series_url"])
        for product in parse_redapple_series_page(html, series_meta):
            if product["detail_url"] in seen_urls:
                continue
            product_id = product["detail_url"].rstrip("/").split("/")[-1].split(".")[0]
            if product_ids and product_id not in product_ids:
                continue
            seen_urls.add(product["detail_url"])
            detail_html = fetch(product["detail_url"])
            detail = parse_redapple_detail_page(detail_html)
            row = {
                "crawl_date": TODAY,
                "brand": "红苹果",
                "product_id": product_id,
                "major_category": product["major_category"],
                "major_category_url": product["major_category_url"],
                "series_name": product["series_name"],
                "series_summary": product["series_summary"],
                "series_url": product["series_url"],
                "series_cover_image_url": product["series_cover_image_url"],
                "series_declared_product_count": product["series_declared_product_count"],
                "product_name": detail.get("product_name") or product["list_title"],
                "list_title": product["list_title"],
                "model": detail.get("型号", ""),
                "style": detail.get("风格", ""),
                "material": detail.get("材质", ""),
                "color": detail.get("颜色", ""),
                "specification": detail.get("规格", ""),
                "description_text": detail.get("description_text", ""),
                "list_image_url": product["list_image_url"],
                "hover_image_url": product["hover_image_url"],
                "gallery_image_count": detail.get("gallery_image_count", "0"),
                "gallery_image_urls": detail.get("gallery_image_urls", ""),
                "detail_url": product["detail_url"],
            }
            display_image_urls = split_pipe_urls(row["gallery_image_urls"])
            if not display_image_urls:
                # 旧站点有些详情页没有 largimg，此时退回系列列表首图和 hover 图。
                # 这两张图虽然不是详情页图集，但仍属于商品卡片层的产品展示图。
                display_image_urls = dedupe_urls([row["list_image_url"], row["hover_image_url"]])
            attach_display_images(
                row=row,
                image_root=image_dir,
                product_id=product_id,
                image_urls=display_image_urls,
                selection_basis="优先使用前端详情轮换图 largimg 图集；若图集缺失则回退到列表首图和 hover 图",
            )
            product_rows.append(row)
            log_progress(
                "红苹果",
                len(product_rows),
                expected_total,
                started_at,
                f"{row['series_name']} / {row['product_name']}",
            )
            if product_ids and len(product_rows) >= len(product_ids):
                break
        if product_ids and len(product_rows) >= len(product_ids):
            break

    if not product_ids or len(product_rows) < len(product_ids):
        for product in direct_product_rows:
            if product["detail_url"] in seen_urls:
                continue
            product_id = product["detail_url"].rstrip("/").split("/")[-1].split(".")[0]
            if product_ids and product_id not in product_ids:
                continue
            seen_urls.add(product["detail_url"])
            detail_html = fetch(product["detail_url"])
            detail = parse_redapple_detail_page(detail_html)
            row = {
                "crawl_date": TODAY,
                "brand": "红苹果",
                "product_id": product_id,
                "major_category": product["major_category"],
                "major_category_url": product["major_category_url"],
                "series_name": product["series_name"],
                "series_summary": product["series_summary"],
                "series_url": product["series_url"],
                "series_cover_image_url": product["series_cover_image_url"],
                "series_declared_product_count": product["series_declared_product_count"],
                "product_name": detail.get("product_name") or product["list_title"],
                "list_title": product["list_title"],
                "model": detail.get("型号", ""),
                "style": detail.get("风格", ""),
                "material": detail.get("材质", ""),
                "color": detail.get("颜色", ""),
                "specification": detail.get("规格", ""),
                "description_text": detail.get("description_text", ""),
                "list_image_url": product["list_image_url"],
                "hover_image_url": product["hover_image_url"],
                "gallery_image_count": detail.get("gallery_image_count", "0"),
                "gallery_image_urls": detail.get("gallery_image_urls", ""),
                "detail_url": product["detail_url"],
            }
            display_image_urls = split_pipe_urls(row["gallery_image_urls"])
            if not display_image_urls:
                display_image_urls = dedupe_urls([row["list_image_url"], row["hover_image_url"]])
            attach_display_images(
                row=row,
                image_root=image_dir,
                product_id=product_id,
                image_urls=display_image_urls,
                selection_basis="优先使用前端详情轮换图 largimg 图集；若图集缺失则回退到列表首图和 hover 图",
            )
            product_rows.append(row)
            log_progress(
                "红苹果",
                len(product_rows),
                expected_total,
                started_at,
                f"{row['major_category']} / {row['product_name']}",
            )
            if product_ids and len(product_rows) >= len(product_ids):
                break

    if not product_rows:
        if product_ids:
            raise RuntimeError(f"红苹果未抓到指定商品 ID：{', '.join(sorted(product_ids))}")
        raise RuntimeError("红苹果商品明细未解析到任何记录，已停止写入以避免生成空表。")

    product_rows.sort(key=lambda row: (row["major_category"], row["series_name"], row["product_name"]))
    fieldnames = [
        "crawl_date",
        "brand",
        "product_id",
        "major_category",
        "major_category_url",
        "series_name",
        "series_summary",
        "series_url",
        "series_cover_image_url",
        "series_declared_product_count",
        "product_name",
        "list_title",
        "model",
        "style",
        "material",
        "color",
        "specification",
        "description_text",
        "list_image_url",
        "hover_image_url",
        "gallery_image_count",
        "gallery_image_urls",
        "display_image_count",
        "display_image_urls",
        "display_image_local_paths",
        "display_image_selection_basis",
        "detail_url",
    ]
    write_csv(out_dir / "redapple_furniture.csv", product_rows, fieldnames)

    readme = f"""# 红苹果家具数据

- 抓取日期：`{TODAY}`
- 来源官网：[http://www.redapple.com.cn/product/index.aspx](http://www.redapple.com.cn/product/index.aspx)
- 抓取方式：从 6 个空间大类页抓取系列页，再从系列页抓取具体商品详情页。
- 数据量：`{len(product_rows)}` 行

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
- 最终会对 URL 去重、保持原始顺序，并把结果写入 `display_image_*` 字段，同时下载到 `data/images/redapple/{{product_id}}/`。
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    log_completion("红苹果", len(product_rows), started_at)
    return len(product_rows)


def build_zuoyou(out_dir: Path, product_ids: Optional[set[str]] = None) -> int:
    started_at = time.monotonic()
    image_dir = IMAGE_ROOT / "zuoyou"
    api_headers = {"X-SS-API-KEY": ZUOYOU_API_KEY}
    channels = fetch_json_url(f"{ZUOYOU_BASE_URL}/api/v1/channels/{ZUOYOU_SITE_ID}", headers=api_headers)
    channel_by_id = {int(channel["id"]): channel for channel in channels}
    children_map: Dict[int, List[Dict[str, Any]]] = {}
    for channel in channels:
        parent_id = int(channel.get("parentId") or 0)
        children_map.setdefault(parent_id, []).append(channel)
    for siblings in children_map.values():
        siblings.sort(key=lambda item: (int(item.get("taxis") or 0), int(item.get("id") or 0)))

    def collect_leaf_paths(channel_id: int, path: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        descendants = []
        for child in children_map.get(channel_id, []):
            child_id = int(child["id"])
            child_name = clean_text(str(child.get("channelName", "") or ""))
            if child_id in ZUOYOU_EXCLUDED_CHANNEL_IDS or "高端定制" in child_name:
                continue
            child_path = path + [child]
            if children_map.get(child_id):
                descendants.extend(collect_leaf_paths(child_id, child_path))
            else:
                descendants.append(child_path)
        return descendants

    def lineage_from_path(path: List[Dict[str, Any]]) -> Tuple[str, str, str]:
        if not path:
            return "", "", ""
        top_brand = clean_text(str(path[0].get("channelName", "") or ""))
        remainder = path[1:]
        if not remainder:
            return top_brand, "", ""

        first = remainder[0]
        first_name = clean_text(str(first.get("channelName", "") or ""))
        first_type = clean_text(str(first.get("attributionType", "") or ""))
        if first_type == "serie":
            return top_brand, "", first_name
        if len(remainder) >= 2:
            return top_brand, first_name, clean_text(str(remainder[1].get("channelName", "") or ""))
        return top_brand, first_name, ""

    def fetch_channel_contents(channel_id: int) -> List[Dict[str, Any]]:
        page = 1
        per_page = 100
        contents: List[Dict[str, Any]] = []
        while True:
            payload = {
                "siteId": ZUOYOU_SITE_ID,
                "wheres": [{"column": "ChannelId", "operator": "In", "value": str(channel_id)}],
                "page": page,
                "perPage": per_page,
            }
            response = post_json_url(f"{ZUOYOU_BASE_URL}/api/v1/contents", payload, headers=api_headers)
            page_items = response.get("contents") or []
            contents.extend(page_items)
            total_count = int(response.get("totalCount") or 0)
            if len(contents) >= total_count or not page_items:
                break
            page += 1
        return contents

    rows: List[Dict[str, str]] = []
    leaf_paths = collect_leaf_paths(ZUOYOU_GOODS_ROOT_ID, [])
    seen_product_ids = set()
    expected_total = len(product_ids) if product_ids else 0
    channel_items_cache: List[Tuple[List[Dict[str, Any]], int, str, str, str, List[Dict[str, Any]]]] = []

    for path in leaf_paths:
        leaf = path[-1]
        leaf_channel_id = int(leaf["id"])
        top_brand, subbrand, series_name = lineage_from_path(path)
        list_items = fetch_channel_contents(leaf_channel_id)
        if product_ids:
            list_items = [item for item in list_items if str(item.get("id", "")) in product_ids]
        else:
            expected_total += len(list_items)
        channel_items_cache.append((path, leaf_channel_id, top_brand, subbrand, series_name, list_items))

    for path, leaf_channel_id, top_brand, subbrand, series_name, list_items in channel_items_cache:
        for item in list_items:
            product_id = int(item["id"])
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)

            detail = fetch_json_url(
                f"{ZUOYOU_BASE_URL}/api/v1/contents/{ZUOYOU_SITE_ID}/{leaf_channel_id}/{product_id}",
                headers=api_headers,
            )
            product_title = clean_text(str(detail.get("title", "") or item.get("title", "") or ""))
            product_code = extract_zuoyou_product_code(product_title, str(detail.get("goodCode", "") or ""))
            product_name = infer_zuoyou_product_name(product_title, product_code)
            description_text = clean_text(str(detail.get("describe", "") or ""))
            design_text = clean_text(str(detail.get("design", "") or ""))
            specifications = clean_text(str(detail.get("specifications", "") or ""))
            specific_material = clean_text(str(detail.get("specificMaterial", "") or ""))
            category_inferred, category_basis = infer_zuoyou_category(
                top_brand=top_brand,
                subbrand=subbrand,
                series_name=series_name,
                product_title=product_title,
                product_name=product_name,
                description_text=description_text,
                design_text=design_text,
                specifications=specifications,
                material_text=specific_material,
            )
            gallery_urls = extract_zuoyou_gallery_urls(detail)
            # 左右家居详情接口已经把前端产品图集分散在 imageUrl / imageUrl1..n，
            # 这就是详情页轮换图来源，因此不需要再从正文或介绍区猜图。
            primary_image_url = gallery_urls[0] if gallery_urls else ""
            row = {
                "crawl_date": TODAY,
                "brand": "左右家居",
                "top_brand": top_brand,
                "subbrand": subbrand,
                "series_name": series_name,
                "channel_path_names": " > ".join(clean_text(str(node.get("channelName", "") or "")) for node in path),
                "channel_path_ids": " > ".join(str(int(node["id"])) for node in path),
                "channel_id": str(leaf_channel_id),
                "product_id": str(product_id),
                "product_title": product_title,
                "product_code": product_code,
                "product_name_inferred": product_name,
                "category_inferred": category_inferred,
                "category_inference_basis": category_basis,
                "style": clean_text(str(detail.get("style", "") or "")),
                "color": clean_text(str(detail.get("goodColor", "") or "")),
                "fabric": clean_text(str(detail.get("fabric", "") or "")),
                "detailed_fabric": clean_text(str(detail.get("detailedFabric", "") or "")),
                "specifications": specifications,
                "specific_material": specific_material,
                "description_text": description_text,
                "design_highlights": design_text,
                "primary_image_url": primary_image_url,
                "gallery_image_count": str(len(gallery_urls)),
                "gallery_image_urls": " | ".join(gallery_urls),
                "detail_url": f"{ZUOYOU_BASE_URL}/good.html?parentId={leaf_channel_id}&id={product_id}",
                "source_page_url": f"{ZUOYOU_BASE_URL}/goods.html",
                "source_api_list_channel_ids": str(leaf_channel_id),
            }
            attach_display_images(
                row=row,
                image_root=image_dir,
                product_id=str(product_id),
                # 当接口图集为空时回退主图，保证图片目录和 CSV 仍然有可追踪的产品图入口。
                image_urls=gallery_urls or ([primary_image_url] if primary_image_url else []),
                selection_basis="优先使用前端详情图集字段 imageUrl / imageUrl1..n；若图集为空则回退到主图",
            )
            rows.append(row)
            log_progress("左右家居", len(rows), expected_total, started_at, f"product_id={product_id}")
            if product_ids and len(rows) >= len(product_ids):
                break
        if product_ids and len(rows) >= len(product_ids):
            break

    if product_ids and not rows:
        raise RuntimeError(f"左右家居未抓到指定商品 ID：{', '.join(sorted(product_ids))}")

    rows.sort(
        key=lambda row: (
            row["top_brand"],
            row["subbrand"],
            row["series_name"],
            row["product_title"],
            int(row["product_id"]),
        )
    )
    fieldnames = [
        "crawl_date",
        "brand",
        "top_brand",
        "subbrand",
        "series_name",
        "channel_path_names",
        "channel_path_ids",
        "channel_id",
        "product_id",
        "product_title",
        "product_code",
        "product_name_inferred",
        "category_inferred",
        "category_inference_basis",
        "style",
        "color",
        "fabric",
        "detailed_fabric",
        "specifications",
        "specific_material",
        "description_text",
        "design_highlights",
        "primary_image_url",
        "gallery_image_count",
        "gallery_image_urls",
        "display_image_count",
        "display_image_urls",
        "display_image_local_paths",
        "display_image_selection_basis",
        "detail_url",
        "source_page_url",
        "source_api_list_channel_ids",
    ]
    write_csv(out_dir / "zuoyou_sofa_furniture.csv", rows, fieldnames)

    readme = f"""# 左右家居家具数据

- 抓取日期：`{TODAY}`
- 来源官网：[https://www.zuoyou-sofa.com/goods.html](https://www.zuoyou-sofa.com/goods.html)
- 抓取方式：调用官网内容接口 `/api/v1/channels/317` 枚举产品树，再按叶子频道调用 `/api/v1/contents` 与 `/api/v1/contents/317/{{channelId}}/{{id}}` 抓取详情。
- 当前数据量：`{len(rows)}` 行

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
- 最终会对 URL 去重、保持原始顺序，并把结果写入 `display_image_*` 字段，同时下载到 `data/images/zuoyou/{{product_id}}/`。
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    log_completion("左右家居", len(rows), started_at)
    return len(rows)


def main() -> None:
    dirs = ensure_dirs()
    selected, product_ids = parse_cli_args(sys.argv[1:])

    summary_path = PROJECT_ROOT / "build_summary.json"
    existing_summary: Dict[str, int] = {}
    if summary_path.exists():
        existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    summary = {
        "landbond_rows": existing_summary.get("landbond_rows", 0),
        "redapple_rows": existing_summary.get("redapple_rows", 0),
        "zuoyou_rows": existing_summary.get("zuoyou_rows", 0),
    }
    if "landbond" in selected:
        summary["landbond_rows"] = build_landbond(dirs["landbond"], product_ids=product_ids)
    if "redapple" in selected:
        summary["redapple_rows"] = build_redapple(dirs["redapple"], product_ids=product_ids)
    if "zuoyou" in selected:
        summary["zuoyou_rows"] = build_zuoyou(dirs["zuoyou_sofa"], product_ids=product_ids)

    (PROJECT_ROOT / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
