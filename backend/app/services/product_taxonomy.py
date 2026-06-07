import json
import re
import unicodedata
from typing import Any

PROFILE_DIMENSIONS = ("categories", "spaces", "styles", "colors", "materials", "brands")

PRODUCT_CATEGORY_TERMS = {
    "sofa": [
        "沙发",
        "沙發",
        "贵妃",
        "躺椅",
        "sofa",
        "couch",
        "sectional",
        "recliner",
        "loveseat",
        "ソファ",
        "ソファー",
        "カウチ",
        "소파",
        "쇼파",
        "canape",
        "divan",
    ],
    "dining_table": [
        "餐桌",
        "饭桌",
        "餐台",
        "dining table",
        "dining desk",
        "mesa de comedor",
        "table a manger",
        "table de salle a manger",
        "ダイニングテーブル",
        "食卓",
        "식탁",
    ],
    "dining_chair": [
        "餐椅",
        "饭椅",
        "dining chair",
        "silla de comedor",
        "chaise de salle a manger",
        "ダイニングチェア",
        "食卓椅",
        "식탁 의자",
    ],
    "bed": ["双人床", "单人床", "婚床", "床", "bed", "cama", "lit", "ベッド", "침대"],
    "nightstand": [
        "床头柜",
        "床頭櫃",
        "nightstand",
        "bedside table",
        "mesita de noche",
        "mesa de noche",
        "table de chevet",
        "ナイトテーブル",
        "ベッドサイド",
        "협탁",
    ],
    "coffee_table": [
        "茶几",
        "茶桌",
        "茶台",
        "边几",
        "邊几",
        "边幾",
        "邊幾",
        "角几",
        "花几",
        "方几",
        "大方几",
        "休闲几",
        "圆几",
        "圓几",
        "圓幾",
        "异形几",
        "異形几",
        "異形幾",
        "背几",
        "背幾",
        "tea table",
        "coffee table",
        "side table",
        "end table",
        "mesa de centro",
        "mesa auxiliar",
        "table basse",
        "table d'appoint",
        "ローテーブル",
        "サイドテーブル",
        "커피 테이블",
        "사이드 테이블",
    ],
    "tv_cabinet": [
        "电视柜",
        "電視櫃",
        "电视机柜",
        "tv cabinet",
        "tv stand",
        "media console",
        "mueble tv",
        "meuble tv",
        "テレビ台",
        "tvボード",
        "거실장",
        "tv장",
    ],
    "cabinet": [
        "储物柜",
        "儲物櫃",
        "收纳柜",
        "收納櫃",
        "边柜",
        "邊櫃",
        "斗柜",
        "斗櫃",
        "柜",
        "櫃",
        "cabinet",
        "storage cabinet",
        "commode",
        "dresser",
        "aparador",
        "armario",
        "buffet",
        "rangement",
        "キャビネット",
        "収納",
        "수납장",
        "서랍장",
    ],
    "wardrobe": [
        "衣柜",
        "衣櫃",
        "wardrobe",
        "closet",
        "armoire",
        "armario ropero",
        "クローゼット",
        "ワードローブ",
        "옷장",
    ],
    "desk": [
        "书桌",
        "書桌",
        "办公桌",
        "辦公桌",
        "书台",
        "書台",
        "写字桌",
        "寫字桌",
        "desk",
        "office desk",
        "bureau",
        "escritorio",
        "デスク",
        "テスク",
        "机",
        "책상",
    ],
    "bookshelf": [
        "书柜",
        "書櫃",
        "书架",
        "書架",
        "书橱",
        "書櫥",
        "bookcase",
        "bookshelf",
        "bibliotheque",
        "estanteria",
        "本棚",
        "書棚",
        "책장",
        "책꽂이",
    ],
    "bar": [
        "吧台",
        "吧椅",
        "bar table",
        "bar stool",
        "barra",
        "taburete",
        "table de bar",
        "bar",
        "バーテーブル",
        "바 테이블",
        "바 의자",
    ],
    "chair": [
        "休闲椅",
        "单椅",
        "椅子",
        "椅",
        "chair",
        "armchair",
        "silla",
        "fauteuil",
        "chaise",
        "チェア",
        "의자",
    ],
    "mattress": ["床垫", "床墊", "mattress", "matelas", "colchon", "マットレス", "매트리스"],
    "bedding": [
        "床品",
        "床上用品",
        "bedding",
        "bed linen",
        "linge de lit",
        "ropa de cama",
        "寝具",
        "침구",
    ],
    "dressing_table": [
        "梳妆台",
        "梳妝台",
        "妆台",
        "妝台",
        "dressing table",
        "vanity table",
        "tocador",
        "coiffeuse",
        "ドレッサー",
        "화장대",
    ],
    "coat_rack": [
        "衣帽架",
        "coat rack",
        "coat stand",
        "porte manteau",
        "perchero",
        "コートラック",
        "옷걸이",
    ],
    "magazine_rack": [
        "杂志架",
        "雜誌架",
        "饰架",
        "飾架",
        "magazine rack",
        "display rack",
        "porte revues",
        "revistero",
        "マガジンラック",
        "잡지꽂이",
    ],
}

SPACE_TERMS = {
    "living_room": [
        "客厅",
        "客廳",
        "起居室",
        "living room",
        "sala",
        "sala de estar",
        "salon",
        "リビング",
        "居間",
        "거실",
    ],
    "dining_room": [
        "餐厅",
        "餐廳",
        "饭厅",
        "飯廳",
        "dining room",
        "comedor",
        "salle a manger",
        "ダイニング",
        "食堂",
        "식당",
        "다이닝룸",
    ],
    "bedroom": [
        "卧室",
        "臥室",
        "主卧",
        "主臥",
        "bedroom",
        "dormitorio",
        "chambre",
        "寝室",
        "ベッドルーム",
        "침실",
    ],
    "study": [
        "书房",
        "書房",
        "办公室",
        "辦公室",
        "study",
        "office",
        "bureau",
        "estudio",
        "書斎",
        "オフィス",
        "서재",
        "사무실",
    ],
    "entryway": [
        "玄关",
        "玄關",
        "门厅",
        "門廳",
        "entryway",
        "foyer",
        "entree",
        "recibidor",
        "玄関",
        "현관",
    ],
}

STYLE_TERMS = {
    "modern": [
        "现代",
        "現代",
        "现代简约",
        "現代簡約",
        "modern",
        "contemporary",
        "moderno",
        "moderne",
        "モダン",
        "현대",
        "모던",
    ],
    "minimalist": [
        "极简",
        "極簡",
        "简约",
        "簡約",
        "minimalist",
        "minimal",
        "minimale",
        "minimalista",
        "ミニマル",
        "シンプル",
        "미니멀",
        "심플",
    ],
    "luxury": [
        "轻奢",
        "輕奢",
        "高端",
        "奢华",
        "奢華",
        "luxury",
        "premium",
        "lujo",
        "lujoso",
        "luxe",
        "ラグジュアリー",
        "高級",
        "럭셔리",
        "고급",
    ],
    "nordic": ["北欧", "北歐", "nordic", "scandinavian", "escandinavo", "scandinave", "북유럽"],
    "chinese": [
        "中式",
        "新中式",
        "chinese style",
        "oriental",
        "estilo chino",
        "style chinois",
        "中国風",
        "중식",
        "중국식",
    ],
    "japanese": [
        "日式",
        "原木风",
        "原木風",
        "japanese",
        "japandi",
        "japones",
        "japonais",
        "和風",
        "日本風",
        "일본식",
    ],
    "vintage": [
        "复古",
        "復古",
        "中古",
        "retro",
        "vintage",
        "clasico",
        "classique",
        "レトロ",
        "ヴィンテージ",
        "복고",
        "빈티지",
    ],
    "french": ["法式", "french", "frances", "francais", "フレンチ", "프렌치"],
    "italian": ["意式", "italian", "italiano", "italien", "イタリアン", "이탈리안"],
}

COLOR_TERMS = {
    "white": [
        "白色",
        "米白",
        "奶油",
        "象牙",
        "白",
        "ivory",
        "white",
        "cream",
        "blanco",
        "blanca",
        "blanc",
        "blanche",
        "白い",
        "ホワイト",
        "흰색",
        "하얀",
        "화이트",
    ],
    "black": [
        "黑色",
        "雅黑",
        "黑",
        "black",
        "negro",
        "noir",
        "黒",
        "ブラック",
        "검정",
        "검은색",
        "블랙",
    ],
    "gray": ["灰色", "银灰", "銀灰", "灰", "grey", "gray", "gris", "グレー", "회색", "그레이"],
    "brown": [
        "棕色",
        "咖啡",
        "褐色",
        "棕",
        "brown",
        "cafe",
        "marron",
        "brun",
        "ブラウン",
        "茶色",
        "갈색",
        "브라운",
    ],
    "wood": [
        "原木",
        "木色",
        "胡桃",
        "柚木",
        "樱桃木",
        "櫻桃木",
        "walnut",
        "teak",
        "cherry wood",
        "wood",
        "madera",
        "bois",
        "木目",
        "ウッド",
        "원목",
        "월넛",
    ],
    "red": [
        "红色",
        "紅色",
        "酒红",
        "酒紅",
        "红",
        "紅",
        "red",
        "rojo",
        "rouge",
        "赤",
        "レッド",
        "빨간",
        "빨강",
        "레드",
    ],
    "blue": [
        "蓝色",
        "藍色",
        "蓝",
        "藍",
        "blue",
        "azul",
        "bleu",
        "青",
        "ブルー",
        "파란",
        "파랑",
        "블루",
    ],
    "green": [
        "绿色",
        "綠色",
        "绿",
        "綠",
        "green",
        "verde",
        "vert",
        "緑",
        "グリーン",
        "초록",
        "녹색",
        "그린",
    ],
    "purple": [
        "紫色",
        "紫",
        "purple",
        "violet",
        "morado",
        "morada",
        "violeta",
        "violette",
        "パープル",
        "보라",
        "보라색",
        "퍼플",
    ],
    "pink": ["粉色", "粉", "pink", "rosa", "rose", "ピンク", "분홍", "핑크"],
    "yellow": [
        "黄色",
        "黃色",
        "黄",
        "黃",
        "yellow",
        "amarillo",
        "jaune",
        "イエロー",
        "노랑",
        "옐로우",
    ],
    "beige": ["米色", "杏色", "卡其", "beige", "khaki", "arena", "ベージュ", "베이지"],
}

MATERIAL_TERMS = {
    "leather": [
        "真皮",
        "牛皮",
        "皮质",
        "皮質",
        "皮",
        "leather",
        "piel",
        "cuero",
        "cuir",
        "革",
        "レザー",
        "가죽",
    ],
    "fabric": [
        "布艺",
        "布藝",
        "布",
        "绒",
        "絨",
        "fabric",
        "cloth",
        "tela",
        "textil",
        "tissu",
        "ファブリック",
        "패브릭",
        "원단",
    ],
    "solid_wood": [
        "实木",
        "實木",
        "原木",
        "solid wood",
        "madera maciza",
        "bois massif",
        "無垢材",
        "木製",
        "원목",
    ],
    "walnut": ["胡桃", "黑胡桃", "walnut", "nogal", "noyer", "ウォールナット", "월넛"],
    "teak": ["柚木", "teak", "teca", "teck", "チーク", "티크"],
    "stone": [
        "岩板",
        "大理石",
        "石",
        "slate",
        "marble",
        "stone",
        "piedra",
        "marbre",
        "セラミック",
        "암판",
        "대리석",
    ],
    "metal": ["金属", "金屬", "五金", "metal", "metalico", "メタル", "금속"],
}

BRAND_TERMS = {
    "landbond": ["联邦", "聯邦", "联邦家私", "聯邦家私", "landbond"],
    "redapple": ["红苹果", "紅蘋果", "red apple", "redapple"],
    "zuoyou": ["左右", "左右沙发", "左右沙發", "左右家居", "zuoyou", "zuo you"],
}

TAXONOMY_TABLES = {
    "categories": PRODUCT_CATEGORY_TERMS,
    "spaces": SPACE_TERMS,
    "styles": STYLE_TERMS,
    "colors": COLOR_TERMS,
    "materials": MATERIAL_TERMS,
    "brands": BRAND_TERMS,
}

CATEGORY_EXCLUSION_TERMS = {
    "sofa": [
        "沙发背柜",
        "沙發背櫃",
        "沙发柜",
        "沙發櫃",
        "沙发背几",
        "沙發背幾",
        "sofa back cabinet",
        "sofa console",
    ],
    "desk": [
        "书桌椅",
        "書桌椅",
        "办公椅",
        "辦公椅",
        "书房椅",
        "書房椅",
        "desk chair",
        "office chair",
        "study chair",
    ],
    "bed": ["床头柜", "床頭櫃", "床垫", "床墊", "nightstand", "mattress"],
    "cabinet": ["电视柜", "電視櫃", "床头柜", "床頭櫃", "书柜", "書櫃", "衣柜", "衣櫃"],
    "dining_table": ["餐椅", "dining chair"],
    "chair": ["餐桌", "dining table"],
    "dressing_table": ["餐桌", "茶几", "coffee table", "dining table"],
}

SPECIFIC_CATEGORY_ORDER = [
    "nightstand",
    "tv_cabinet",
    "dining_chair",
    "coffee_table",
    "dining_table",
    "bookshelf",
    "wardrobe",
    "mattress",
    "bedding",
    "dressing_table",
    "desk",
    "sofa",
    "bed",
    "bar",
    "coat_rack",
    "magazine_rack",
    "chair",
    "cabinet",
]


def normalize_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).lower()
    without_marks = "".join(
        ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn"
    )
    spaced = re.sub(r"[\s\-_、，,./|:;；：()\[\]{}]+", " ", without_marks)
    return re.sub(r"\s+", " ", spaced).strip()


def contains_any(text: str, terms: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(_contains_term(normalized, normalize_text(term)) for term in terms if term)


def _contains_term(normalized_text: str, normalized_term: str) -> bool:
    if not normalized_text or not normalized_term:
        return False
    # Latin terms need token boundaries; otherwise "couch" matches French "coucher".
    if re.fullmatch(r"[a-z0-9 ]+", normalized_term):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_term in normalized_text


def canonicalize_value(dimension: str, value: Any) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    table = TAXONOMY_TABLES.get(dimension, {})
    if normalized in table:
        return normalized
    for key, terms in table.items():
        if normalized == normalize_text(key) or normalized in {
            normalize_text(term) for term in terms
        }:
            return key
    return ""


def canonicalize_values(dimension: str, values: Any, limit: int = 6) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list | tuple | set):
        raw_values = list(values)
    else:
        return []
    out: list[str] = []
    for value in raw_values:
        canonical = canonicalize_value(dimension, value)
        if canonical and canonical not in out:
            out.append(canonical)
    return out[:limit]


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            return [x.strip() for x in value.split(",") if x.strip()]
    return []


def product_category_values(product: dict[str, Any]) -> list[str]:
    primary = str(product.get("primary_category") or "").strip()
    secondary = parse_json_list(
        product.get("secondary_categories") or product.get("secondary_categories_json")
    )
    values = [primary, *secondary]
    return [v for v in values if v]


def normalized_product_values(product: dict[str, Any], dimension: str) -> list[str]:
    if dimension == "categories":
        return product_category_values(product)
    field_map = {
        "spaces": ["normalized_space"],
        "styles": ["normalized_style"],
        "colors": ["normalized_color"],
        "materials": ["normalized_materials", "normalized_materials_json"],
        "brands": ["normalized_brand"],
    }
    values: list[str] = []
    for field in field_map.get(dimension, []):
        raw = product.get(field)
        if field.endswith("_json") or isinstance(raw, list):
            values.extend(parse_json_list(raw))
        elif raw:
            values.append(str(raw))
    return [v for v in values if v]


def match_normalized_product_value(
    product: dict[str, Any], dimension: str, value: str
) -> bool | None:
    values = normalized_product_values(product, dimension)
    if not values:
        return None
    return value in values


def _joined_product_text(product: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts: list[str] = []
    for key in keys:
        value = str(product.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    translations = product.get("translations") or {}
    if isinstance(translations, dict):
        for entry in translations.values():
            if not isinstance(entry, dict):
                continue
            for key in keys:
                value = str(entry.get(key) or "").strip()
                if value and value not in parts:
                    parts.append(value)
    return "\n".join(parts)


def infer_primary_category(product: dict[str, Any]) -> tuple[str, float, str]:
    category_text = _joined_product_text(
        product,
        (
            "category",
            "name",
            "product_name",
            "series",
            "series_name",
            "space",
            "description",
            "description_text",
        ),
    )
    normalized = normalize_text(category_text)
    for category in SPECIFIC_CATEGORY_ORDER:
        if contains_any(normalized, CATEGORY_EXCLUSION_TERMS.get(category, [])):
            continue
        if contains_any(normalized, PRODUCT_CATEGORY_TERMS[category]):
            return category, 0.78, f"matched category terms for {category}"
    return "", 0.0, "no category terms matched"


def _infer_first_dimension(product: dict[str, Any], dimension: str, keys: tuple[str, ...]) -> str:
    text = _joined_product_text(product, keys)
    for value, terms in TAXONOMY_TABLES[dimension].items():
        if contains_any(text, terms):
            return value
    return ""


def _infer_materials(product: dict[str, Any]) -> list[str]:
    text = _joined_product_text(
        product,
        ("material", "description", "description_text", "detail_content", "detail_content_text"),
    )
    out: list[str] = []
    for value, terms in MATERIAL_TERMS.items():
        if contains_any(text, terms):
            out.append(value)
    return out[:4]


def infer_product_metadata(product: dict[str, Any]) -> dict[str, Any]:
    category, category_confidence, reason = infer_primary_category(product)
    brand = canonicalize_value("brands", product.get("brand"))
    return {
        "primary_category": category,
        "secondary_categories": [],
        "normalized_brand": brand,
        "normalized_space": _infer_first_dimension(
            product,
            "spaces",
            (
                "space",
                "name",
                "product_name",
                "series",
                "series_name",
                "description",
                "description_text",
            ),
        ),
        "normalized_style": _infer_first_dimension(
            product,
            "styles",
            (
                "style",
                "name",
                "product_name",
                "series",
                "series_name",
                "description",
                "description_text",
            ),
        ),
        "normalized_color": _infer_first_dimension(
            product,
            "colors",
            (
                "color",
                "name",
                "product_name",
                "series",
                "series_name",
                "description",
                "description_text",
            ),
        ),
        "normalized_materials": _infer_materials(product),
        "category_confidence": category_confidence,
        "classification_source": "rules",
        "classification_reason": reason,
    }


def apply_inferred_metadata(fields: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(fields)
    metadata = infer_product_metadata(
        {
            "brand": enriched.get("brand", ""),
            "name": enriched.get("product_name", ""),
            "product_name": enriched.get("product_name", ""),
            "series": enriched.get("series_name", ""),
            "series_name": enriched.get("series_name", ""),
            "space": enriched.get("space", ""),
            "style": enriched.get("style", ""),
            "color": enriched.get("color", ""),
            "material": enriched.get("material", ""),
            "description": enriched.get("description_text", ""),
            "description_text": enriched.get("description_text", ""),
            "detail_content": enriched.get("detail_content_text", ""),
            "detail_content_text": enriched.get("detail_content_text", ""),
        }
    )
    enriched.update(
        {
            "primary_category": metadata["primary_category"],
            "secondary_categories_json": json.dumps(
                metadata["secondary_categories"], ensure_ascii=False
            ),
            "normalized_brand": metadata["normalized_brand"],
            "normalized_space": metadata["normalized_space"],
            "normalized_style": metadata["normalized_style"],
            "normalized_color": metadata["normalized_color"],
            "normalized_materials_json": json.dumps(
                metadata["normalized_materials"], ensure_ascii=False
            ),
            "category_confidence": metadata["category_confidence"],
            "classification_source": metadata["classification_source"],
            "classification_reason": metadata["classification_reason"],
        }
    )
    return enriched
