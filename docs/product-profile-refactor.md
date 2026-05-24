# Product Recommendation and Scene Profile Refactor

## Goal

This refactor improves how the agent understands customer wording for two paths:

- Product recommendation
- Product scene image generation

Intent routing still uses the existing logic. The new layer only runs after the request is already classified as product recommendation or scene image generation.

## Model Choice

Recommended profile parser model:

- `qwen3.6-flash` through DashScope OpenAI-compatible API
- Fallback compatible models: `qwen-flash-latest`, `qwen-turbo-latest`
- Low-confidence retry candidate: `qwen3.6-plus` or `qwen-plus-latest`

The parser is a short-text JSON extraction task, so low latency and strict structured output matter more than long-context reasoning. Qwen/DashScope also fits the current backend because the existing OpenAI-compatible client already supports DashScope `enable_thinking=false`.

Configuration locations:

- Environment defaults: `backend/.env`
- Example fields: `backend/.env.example`
- Admin/API settings: `/api/settings/llm`
- New optional fields:
  - `PROFILE_LLM_PROVIDER`
  - `PROFILE_LLM_API_KEY`
  - `PROFILE_LLM_BASE_URL`
  - `PROFILE_LLM_MODEL`

If these fields are empty, the profile parser reuses the existing `OPENAI_*` / `llm_*` configuration.

## Architecture

The new flow is a hybrid architecture:

```text
customer message
-> existing intent classifier
-> profile parser small model
-> canonical ProductRequestProfile or SceneRequestProfile
-> standardized product metadata filtering
-> existing LLM rerank / scene generation
-> existing timeout and fallback behavior
```

The important change is that the LLM no longer directly guesses products from the full catalog. It first converts the user message into canonical fields, then the backend filters against standardized product metadata.

## ProductRequestProfile

The product recommendation profile uses fixed enums:

- `categories`: `sofa`, `dining_table`, `dining_chair`, `bed`, `nightstand`, `coffee_table`, `tv_cabinet`, `cabinet`, `wardrobe`, `desk`, `bookshelf`, `bar`, `chair`, `mattress`, `bedding`, `dressing_table`, `coat_rack`, `magazine_rack`
- `spaces`: `living_room`, `dining_room`, `bedroom`, `study`, `entryway`
- `styles`: `modern`, `minimalist`, `luxury`, `nordic`, `chinese`, `japanese`, `vintage`, `french`, `italian`
- `colors`: `white`, `black`, `gray`, `brown`, `wood`, `red`, `blue`, `green`, `purple`, `pink`, `yellow`, `beige`
- `materials`: `leather`, `fabric`, `solid_wood`, `walnut`, `teak`, `stone`, `metal`
- `brands`: `landbond`, `redapple`, `zuoyou`

Example:

```json
{
  "intent": "product_recommendation",
  "language": "zh-Hans",
  "categories": ["sofa"],
  "colors": ["purple"],
  "styles": ["chinese"],
  "materials": [],
  "spaces": [],
  "brands": [],
  "hard_constraints": ["categories", "colors", "styles"],
  "confidence": 0.91,
  "needs_human": false
}
```

If explicit constraints cannot be fully satisfied by inventory, the agent must say that clearly instead of forcing unrelated products.

## SceneRequestProfile

Scene generation profile extracts product reference and requested scene separately:

```json
{
  "intent": "scene_image_request",
  "language": "zh-Hans",
  "is_scene_request": true,
  "target_product_slot": 3,
  "target_product_id": null,
  "scene_name": "餐厅",
  "style_hint": "中式复古",
  "requirements": ["中式", "复古", "餐厅"],
  "confidence": 0.88,
  "needs_human": false
}
```

This prevents the previous issue where the product's default database space overrode the customer's requested scene.

## Standardized Product Metadata

`product_entries` now has standardized fields:

- `primary_category`
- `secondary_categories_json`
- `normalized_brand`
- `normalized_space`
- `normalized_style`
- `normalized_color`
- `normalized_materials_json`
- `category_confidence`
- `classification_source`
- `classification_reason`

Existing products are backfilled by:

```bash
docker compose exec -T backend python scripts/backfill_product_metadata.py
```

New imports through `scripts/import_products.py` also infer these fields.

## Fallback Behavior

The refactor preserves existing behavior:

- If profile parsing times out or fails, local multilingual rules are used.
- Product matching still has LLM timeout fallback to local ranking.
- Scene generation timeout behavior is unchanged.
- Mode 1, mode 2, mode 3 behavior is unchanged.
- Recommendation state is still saved for follow-up scene image requests.
- Multilingual customer replies are still localized through the existing language system.

Low-confidence handling:

- High confidence: execute normally.
- Low confidence with `needs_human=true`: transfer to human service.
- Inventory mismatch: explain partial mismatch and recommend close alternatives only.

## Main Files

- `backend/app/services/profile_parser_service.py`: parses product and scene request profiles.
- `backend/app/services/product_taxonomy.py`: canonical taxonomy and deterministic product metadata inference.
- `backend/app/services/llm_service.py`: profile model settings, structured product matching, constraint notice handling.
- `backend/app/telegram_bot.py`: integrates profile parsing into product recommendation and scene generation flow.
- `backend/scripts/backfill_product_metadata.py`: backfills standardized metadata for existing products.
- `backend/scripts/import_products.py`: fills standardized metadata during import.

## Verification

Commands used:

```bash
docker compose exec -T backend python -m unittest discover -s tests -q
docker compose exec -T backend python -m py_compile app/services/profile_parser_service.py app/services/product_taxonomy.py app/services/llm_service.py app/telegram_bot.py app/services/product_i18n.py app/services/scene_service.py app/models.py app/schemas.py app/api/router.py scripts/import_products.py scripts/backfill_product_metadata.py
docker compose exec -T backend python scripts/backfill_product_metadata.py
```

Current backfill result: 388 products processed. Empty `primary_category` entries are mostly material/color-board resources or ambiguous products with insufficient source text.
