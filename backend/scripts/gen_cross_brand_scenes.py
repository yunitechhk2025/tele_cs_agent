"""Generate 3 cross-brand scene library examples."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import ProductEntry
from app.services.scene_service import generate_scene_images

COMBOS = [
    {
        "primary_id": 195,
        "related_ids": [386, 384],
        "scene": "客厅",
        "style": "现代新中式",
        "request": "联邦柚木真皮沙发搭配红苹果茶几和电视柜，摆放在现代新中式风格客厅中",
    },
    {
        "primary_id": 366,
        "related_ids": [176, 508],
        "scene": "卧室",
        "style": "现代简约",
        "request": "红苹果大床搭配联邦实木床头柜和左右家居单椅，放在温馨简约卧室中",
    },
    {
        "primary_id": 174,
        "related_ids": [388, 193],
        "scene": "新中式茶室",
        "style": "新中式",
        "request": "联邦新中式茶台搭配红苹果隔厅柜和联邦茶几，放在古典新中式茶室客厅中",
    },
]


async def gen_one(combo):
    async with AsyncSessionLocal() as db:
        primary = await db.get(ProductEntry, combo["primary_id"])
        if not primary:
            print(f"ERROR: product {combo['primary_id']} not found")
            return
        result = await db.execute(select(ProductEntry).order_by(ProductEntry.id))
        entries = result.scalars().all()
        all_products = [
            {
                "id": e.id,
                "name": e.product_name,
                "space": e.space,
                "style": e.style,
                "color": e.color,
                "material": e.material,
                "buy_url": e.buy_url,
                "detail_url": e.detail_url,
            }
            for e in entries
        ]
    t0 = time.time()
    print(f"Starting: primary={primary.product_name[:25]}  scene={combo['scene']}", flush=True)
    record = await generate_scene_images(
        primary_product=primary,
        all_products=all_products,
        user_request=combo["request"],
        scene_name=combo["scene"],
        style_hint=combo["style"],
        related_product_ids=combo["related_ids"],
    )
    elapsed = time.time() - t0
    print(f"Done: id={record.id}  status={record.status}  duration={elapsed:.0f}s", flush=True)


async def main():
    tasks = [gen_one(c) for c in COMBOS]
    await asyncio.gather(*tasks)
    print("All 3 cross-brand scenes generated!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
