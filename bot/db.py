from datetime import date, datetime
def fmt_kg(value):
    try:
        v=float(value)
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    except: return str(value)

"""PostgreSQL access layer for the factory accounting Telegram bot."""
import json
import logging
import asyncpg

logger = logging.getLogger(__name__)
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 10
COMMAND_TIMEOUT = 10.0

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_date DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_date_confirmed BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS loads (
    id BIGSERIAL PRIMARY KEY,
    load_no INTEGER,
    received_date DATE NOT NULL,
    vehicle_no TEXT NOT NULL,
    person_name TEXT NOT NULL,
    items JSONB NOT NULL,
    skidka_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    vozvrat_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE loads ADD COLUMN IF NOT EXISTS load_no INTEGER;

WITH numbered AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY received_date ORDER BY id) AS rn
    FROM loads
)
UPDATE loads l
SET load_no = n.rn
FROM numbered n
WHERE l.id = n.id AND l.load_no IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_loads_date_load_no
ON loads(received_date, load_no);

CREATE TABLE IF NOT EXISTS furnaces (
    id BIGSERIAL PRIMARY KEY,
    furnace_date DATE NOT NULL,
    furnace_type TEXT NOT NULL,
    items JSONB NOT NULL,
    finished_product TEXT NOT NULL DEFAULT '',
    finished_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    scrap_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    loss_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finished_products (
    id BIGSERIAL PRIMARY KEY,
    production_date DATE NOT NULL,
    product TEXT NOT NULL,
    kg NUMERIC(18,3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_finished_products_date ON finished_products(production_date);
CREATE INDEX IF NOT EXISTS idx_finished_products_product ON finished_products(product);

CREATE TABLE IF NOT EXISTS load_adjustments (
    id BIGSERIAL PRIMARY KEY,
    load_id BIGINT NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    material TEXT NOT NULL,
    skidka_percent NUMERIC(10,4) NOT NULL DEFAULT 0,
    vozvrat_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_load_adjustments_load ON load_adjustments(load_id);

CREATE TABLE IF NOT EXISTS furnace_adjustments (
    id BIGSERIAL PRIMARY KEY,
    furnace_id BIGINT NOT NULL REFERENCES furnaces(id) ON DELETE CASCADE,
    material TEXT NOT NULL,
    adjustment_type TEXT NOT NULL CHECK (adjustment_type IN ('skidka','vozvrat')),
    kg NUMERIC(18,3) NOT NULL CHECK (kg >= 0),
    percent NUMERIC(10,4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_furnace_adjustments_furnace ON furnace_adjustments(furnace_id);

CREATE TABLE IF NOT EXISTS sales (
    id BIGSERIAL PRIMARY KEY,
    sale_date DATE NOT NULL,
    product TEXT NOT NULL,
    kg NUMERIC(18,3) NOT NULL,
    sale_price NUMERIC(20,2) NOT NULL,
    cost_price NUMERIC(20,2) NOT NULL,
    revenue NUMERIC(24,2) NOT NULL,
    profit NUMERIC(24,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loads_vehicle ON loads(vehicle_no);
CREATE INDEX IF NOT EXISTS idx_loads_person ON loads(person_name);
CREATE INDEX IF NOT EXISTS idx_loads_date ON loads(received_date);
CREATE INDEX IF NOT EXISTS idx_furnaces_date ON furnaces(furnace_date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
"""

async def create_pool(dsn: str):
    pool = await asyncpg.create_pool(dsn, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE,
                                     command_timeout=COMMAND_TIMEOUT)
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SCHEMA)
    return pool

async def upsert_user(pool, telegram_id, username, first_name):
    await pool.execute("""
        INSERT INTO users (telegram_id, username, first_name)
        VALUES ($1,$2,$3)
        ON CONFLICT (telegram_id) DO UPDATE
        SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_seen=now()
    """, telegram_id, username, first_name)

async def get_active_date(pool, telegram_id, today):
    row = await pool.fetchrow(
        "SELECT active_date, active_date_confirmed FROM users WHERE telegram_id=$1",
        telegram_id
    )
    if not row or row["active_date"] != today or not row["active_date_confirmed"]:
        return None
    return row["active_date"]

async def set_active_date(pool, telegram_id, active_date):
    await pool.execute("""
        UPDATE users SET active_date=$2, active_date_confirmed=TRUE, last_seen=now()
        WHERE telegram_id=$1
    """, telegram_id, active_date)

def _json_items(items):
    out = []
    for x in items:
        out.append({
            "material": str(x["material"]),
            "initial_kg": str(x["initial_kg"]),
            "price": str(x["price"]),
        })
    return out

async def create_load(pool, received_date, vehicle_no, person_name, items, skidka_kg=0, vozvrat_kg=0):
    items_json = _json_items(items)
    total = sum(float(x["initial_kg"]) for x in items_json)
    if total <= 0:
        raise ValueError("Yuk kg 0 dan katta boâlishi kerak")

    # Yuk qabul qilishda skidka/vozvrat 0 boâladi.
    # Raqam kun boâyicha avtomatik 1, 2, 3... qilib beriladi.
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(824731)")
            load_no = await conn.fetchval("""
                SELECT COALESCE(MAX(load_no), 0) + 1
                FROM loads
                WHERE received_date=$1
            """, received_date)
            for x in items_json:
                x["accepted_kg"] = str(round(float(x["initial_kg"]), 3))
            row = await conn.fetchrow("""
                INSERT INTO loads(
                    load_no,received_date,vehicle_no,person_name,items,skidka_kg,vozvrat_kg
                )
                VALUES($1,$2,$3,$4,$5::jsonb,0,0)
                RETURNING id, load_no
            """, int(load_no), received_date, vehicle_no, person_name,
                 json.dumps(items_json, ensure_ascii=False))
            return int(row["id"]), int(row["load_no"])

async def daily_load_total(pool, received_date):
    row = await pool.fetchrow("""
        SELECT COALESCE(SUM(
            (SELECT COALESCE(SUM((item->>'initial_kg')::numeric),0)
             FROM jsonb_array_elements(items) AS item)
        ),0) AS total_kg,
        COUNT(*) AS load_count
        FROM loads
        WHERE received_date=$1
    """, received_date)
    return float(row["total_kg"] or 0), int(row["load_count"] or 0)


def _load(row):
    d = dict(row)
    if isinstance(d["items"], str):
        d["items"] = json.loads(d["items"])
    return d

async def get_load(pool, load_id):
    row = await pool.fetchrow("SELECT * FROM loads WHERE id=$1", load_id)
    return _load(row) if row else None

async def search_loads(pool, text):
    q = f"%{text}%"
    rows = await pool.fetch("""
        SELECT * FROM loads
        WHERE vehicle_no ILIKE $1 OR person_name ILIKE $1
        ORDER BY id DESC LIMIT 20
    """, q)
    return [_load(r) for r in rows]

async def update_load_item_kg(pool, load_id, material, new_kg):
    row = await pool.fetchrow("SELECT items, skidka_kg, vozvrat_kg FROM loads WHERE id=$1 FOR UPDATE", load_id)
    if not row:
        return False
    items = row["items"] if isinstance(row["items"], list) else json.loads(row["items"])
    found = False
    for x in items:
        if str(x.get("material","")).strip().lower() == material.strip().lower():
            x["initial_kg"] = str(new_kg)
            found = True
            break
    if not found:
        return False
    total = sum(float(x["initial_kg"]) for x in items)
    deduction = float(row["skidka_kg"]) + float(row["vozvrat_kg"])
    for x in items:
        initial = float(x["initial_kg"])
        x["accepted_kg"] = str(round(max(0, initial - deduction*initial/total), 3))
    await pool.execute("UPDATE loads SET items=$2::jsonb WHERE id=$1",
                        load_id, json.dumps(items, ensure_ascii=False))
    return True

async def create_furnace(pool, furnace_date, furnace_type, items, finished_product, finished_kg, scrap_kg):
    items_json = [{"material": str(x["material"]), "kg": str(x["kg"])} for x in items]
    input_kg = sum(float(x["kg"]) for x in items_json)
    finished = float(finished_kg); scrap = float(scrap_kg)
    loss = input_kg - finished - scrap
    if input_kg <= 0 or finished < 0 or scrap < 0 or loss < -0.0001:
        raise ValueError("Qozon balansi notoâgâri")
    row = await pool.fetchrow("""
        INSERT INTO furnaces(furnace_date,furnace_type,items,finished_product,finished_kg,scrap_kg,loss_kg)
        VALUES($1,$2,$3::jsonb,$4,$5,$6,$7) RETURNING id
    """, furnace_date, furnace_type, json.dumps(items_json, ensure_ascii=False),
       finished_product, finished, scrap, loss)
    return int(row["id"])

async def update_furnace_item_kg(pool, furnace_id, material, new_kg):
    row = await pool.fetchrow("SELECT items FROM furnaces WHERE id=$1", furnace_id)
    if not row: return False
    items = row["items"] if isinstance(row["items"], list) else json.loads(row["items"])
    found = False
    for x in items:
        if str(x.get("material","")).strip().lower() == material.strip().lower():
            x["kg"] = str(new_kg); found = True; break
    if not found: return False
    input_kg = sum(float(x["kg"]) for x in items)
    f = await pool.fetchrow("SELECT finished_kg, scrap_kg FROM furnaces WHERE id=$1", furnace_id)
    loss = input_kg - float(f["finished_kg"]) - float(f["scrap_kg"])
    if loss < -0.0001: raise ValueError("Yangi kg bilan qozon balansi manfiy chiqmoqda")
    await pool.execute("UPDATE furnaces SET items=$2::jsonb, loss_kg=$3 WHERE id=$1",
                       furnace_id, json.dumps(items, ensure_ascii=False), loss)
    return True

async def update_furnace_result(pool, furnace_id, finished_kg, scrap_kg):
    row = await pool.fetchrow("SELECT items FROM furnaces WHERE id=$1", furnace_id)
    if not row: return False
    items = row["items"] if isinstance(row["items"], list) else json.loads(row["items"])
    input_kg = sum(float(x["kg"]) for x in items)
    loss = float(finished_kg) * 0 + input_kg - float(finished_kg) - float(scrap_kg)
    if loss < -0.0001: raise ValueError("Tayyor + chiqit kirimdan katta")
    await pool.execute("UPDATE furnaces SET finished_kg=$2,scrap_kg=$3,loss_kg=$4 WHERE id=$1",
                       furnace_id, finished_kg, scrap_kg, loss)
    return True

async def create_finished_product(pool, production_date, product, kg):
    row = await pool.fetchrow("""
        INSERT INTO finished_products(production_date, product, kg)
        VALUES($1,$2,$3) RETURNING id
    """, production_date, product, kg)
    return int(row["id"])

async def finished_products_summary(pool):
    rows = await pool.fetch("""
        SELECT product,
               SUM(kg) AS produced_kg
        FROM finished_products
        GROUP BY product
        ORDER BY product
    """)
    sold = await pool.fetch("""
        SELECT product, SUM(kg) AS sold_kg
        FROM sales
        GROUP BY product
    """)
    sold_map = {str(r["product"]).strip().lower(): float(r["sold_kg"] or 0) for r in sold}
    result = []
    for r in rows:
        product = str(r["product"])
        produced = float(r["produced_kg"] or 0)
        sold_kg = sold_map.get(product.strip().lower(), 0)
        result.append({"product": product, "produced_kg": produced,
                       "sold_kg": sold_kg, "stock_kg": produced - sold_kg})
    return result

async def update_finished_product_kg(pool, production_id, new_kg):
    if float(new_kg) <= 0:
        raise ValueError("Kg 0 dan katta boâlishi kerak")
    row = await pool.fetchrow("SELECT id FROM finished_products WHERE id=$1", production_id)
    if not row:
        return False
    await pool.execute("UPDATE finished_products SET kg=$2 WHERE id=$1", production_id, new_kg)
    return True

async def create_sale(pool, sale_date, product, kg, sale_price, cost_price):
    available = await pool.fetchval("""
        SELECT COALESCE((SELECT SUM(fp.kg) FROM finished_products fp
                         WHERE lower(fp.product)=lower($1)),0)
             - COALESCE((SELECT SUM(s.kg) FROM sales s
                         WHERE lower(s.product)=lower($1)),0)
    """, product)
    available = float(available or 0)
    if float(kg) > available + 0.0001:
        raise ValueError(f"Omborda bu tayyor mahsulotdan faqat {fmt_kg(available)} kg bor")
    revenue = kg * sale_price
    profit = kg * (sale_price - cost_price)
    row = await pool.fetchrow("""
        INSERT INTO sales(sale_date,product,kg,sale_price,cost_price,revenue,profit)
        VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id
    """, sale_date, product, kg, sale_price, cost_price, revenue, profit)
    return int(row["id"])

async def update_sale_kg(pool, sale_id, new_kg):
    row = await pool.fetchrow("SELECT sale_price,cost_price FROM sales WHERE id=$1", sale_id)
    if not row: return False
    revenue = float(new_kg) * float(row["sale_price"])
    profit = float(new_kg) * (float(row["sale_price"]) - float(row["cost_price"]))
    await pool.execute("UPDATE sales SET kg=$2,revenue=$3,profit=$4 WHERE id=$1",
                       sale_id, new_kg, revenue, profit)
    return True


async def create_furnace_adjustment(pool, furnace_id, material, adjustment_type, kg):
    kg = Decimal(str(kg))
    if kg <= 0:
        raise ValueError("Kg 0 dan katta boâlishi kerak")
    if adjustment_type not in ("skidka", "vozvrat"):
        raise ValueError("Turi notoâgâri")

    row = await pool.fetchrow("SELECT items FROM furnaces WHERE id=$1", furnace_id)
    if not row:
        raise ValueError("Qozon ID topilmadi")
    items = row["items"] if isinstance(row["items"], list) else json.loads(row["items"])
    material_key = material.strip().lower()
    input_kg = sum(
        Decimal(str(x.get("kg", 0)))
        for x in items
        if str(x.get("material", "")).strip().lower() == material_key
    )
    if input_kg <= 0:
        raise ValueError("Bu material qozonda topilmadi")

    old = await pool.fetchval("""
        SELECT COALESCE(SUM(kg),0)
        FROM furnace_adjustments
        WHERE furnace_id=$1 AND material=$2
    """, furnace_id, material)
    old = Decimal(str(old or 0))
    if old + kg > input_kg:
        raise ValueError(f"{material} uchun skidka+vozvrat {input_kg} kg dan oshmasligi kerak")

    pct = (kg / input_kg) * Decimal("100")
    row = await pool.fetchrow("""
        INSERT INTO furnace_adjustments(furnace_id,material,adjustment_type,kg,percent)
        VALUES($1,$2,$3,$4,$5)
        RETURNING id
    """, furnace_id, material, adjustment_type, kg, pct)
    return int(row["id"])

async def get_furnace_adjustments(pool, furnace_id):
    return await pool.fetch("""
        SELECT id, furnace_id, material, adjustment_type, kg, percent, created_at
        FROM furnace_adjustments
        WHERE furnace_id=$1
        ORDER BY id
    """, furnace_id)

async def furnace_adjustment_summary(pool, furnace_id):
    rows = await get_furnace_adjustments(pool, furnace_id)
    return [dict(r) for r in rows]




async def search_loads_for_adjustment(pool, search_text):
    s = str(search_text or "").strip()
    # Exact date dd.mm.yyyy, otherwise search person/vehicle, otherwise numeric kg.
    rows = []
    try:
        dt = datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        dt = None

    if dt:
        rows = await pool.fetch("""
            SELECT id, load_no, received_date, vehicle_no, person_name, items
            FROM loads WHERE received_date=$1
            ORDER BY load_no NULLS LAST, id
        """, dt)
    else:
        rows = await pool.fetch("""
            SELECT id, load_no, received_date, vehicle_no, person_name, items
            FROM loads
            WHERE vehicle_no ILIKE $1 OR person_name ILIKE $1
            ORDER BY received_date DESC, load_no NULLS LAST, id DESC
            LIMIT 50
        """, f"%{s}%")
        if not rows:
            try:
                kg = Decimal(str(s).replace(",", ".").replace("kg","").strip())
                rows = await pool.fetch("""
                    SELECT id, load_no, received_date, vehicle_no, person_name, items
                    FROM loads
                    WHERE EXISTS (
                      SELECT 1 FROM jsonb_array_elements(items) item
                      WHERE ABS((item->>'initial_kg')::numeric - $1) < 0.0005
                    )
                    ORDER BY received_date DESC, load_no NULLS LAST, id DESC
                    LIMIT 50
                """, kg)
            except Exception:
                rows = []
    out=[]
    for r in rows:
        x=dict(r)
        if isinstance(x["items"],str):
            x["items"]=json.loads(x["items"])
        out.append(x)
    return out

async def set_load_material_adjustment(pool, load_id, material, skidka_percent, vozvrat_kg):
    p=Decimal(str(skidka_percent or 0))
    v=Decimal(str(vozvrat_kg or 0))
    if p<0 or p>100:
        raise ValueError("Skidka foizi 0 dan 100 gacha boâlishi kerak")
    if v<0:
        raise ValueError("Vozvrat kg manfiy boâlmaydi")
    row=await pool.fetchrow("SELECT items FROM loads WHERE id=$1",load_id)
    if not row: raise ValueError("Yuk topilmadi")
    items=row["items"] if isinstance(row["items"],list) else json.loads(row["items"])
    item=next((x for x in items if str(x.get("material",""))==material),None)
    if not item: raise ValueError("Material topilmadi")
    initial=Decimal(str(item.get("initial_kg",0)))
    skidka_kg=initial*p/Decimal("100")
    final=initial-skidka_kg-v
    if final<0:
        raise ValueError("Skidka va vozvrat jami material kgidan oshib ketadi")

    await pool.execute("DELETE FROM load_adjustments WHERE load_id=$1 AND material=$2",load_id,material)
    await pool.execute("""
        INSERT INTO load_adjustments(load_id,material,skidka_percent,vozvrat_kg)
        VALUES($1,$2,$3,$4)
    """,load_id,material,p,v)
    return initial, skidka_kg, v, final

async def recent_load_dates(pool, limit=30):
    rows = await pool.fetch("""
        SELECT received_date, COUNT(*) AS load_count,
               COALESCE(SUM((SELECT COALESCE(SUM((item->>'initial_kg')::numeric),0)
                             FROM jsonb_array_elements(items) AS item)),0) AS total_kg
        FROM loads
        GROUP BY received_date
        ORDER BY received_date DESC
        LIMIT $1
    """, limit)
    return [dict(r) for r in rows]

async def loads_by_date(pool, received_date):
    rows = await pool.fetch("""
        SELECT id, load_no, received_date, vehicle_no, person_name, items
        FROM loads
        WHERE received_date=$1
        ORDER BY load_no NULLS LAST, id
    """, received_date)
    out=[]
    for r in rows:
        x=dict(r)
        if isinstance(x["items"], str):
            x["items"]=json.loads(x["items"])
        out.append(x)
    return out

async def load_material_adjustment_summary(pool, load_id, material):
    row = await pool.fetchrow("""
        SELECT
          COALESCE(SUM(skidka_percent),0) AS skidka_percent,
          COALESCE(SUM(vozvrat_kg),0) AS vozvrat_kg
        FROM load_adjustments
        WHERE load_id=$1 AND material=$2
    """, load_id, material)
    return dict(row) if row else {"skidka_percent":0,"vozvrat_kg":0}

async def create_load_adjustment(pool, load_id, material, skidka_percent, vozvrat_kg):
    p = Decimal(str(skidka_percent or 0))
    v = Decimal(str(vozvrat_kg or 0))
    if p < 0 or p > 100:
        raise ValueError("Skidka foizi 0 dan 100 gacha boâlishi kerak")
    if v < 0:
        raise ValueError("Vozvrat kg manfiy boâlmaydi")
    row = await pool.fetchrow("SELECT items FROM loads WHERE id=$1", load_id)
    if not row:
        raise ValueError("Yuk topilmadi")
    items=row["items"] if isinstance(row["items"],list) else json.loads(row["items"])
    item=next((x for x in items if str(x.get("material",""))==material),None)
    if not item:
        raise ValueError("Bu material tanlangan yukda topilmadi")
    initial=Decimal(str(item.get("initial_kg",0)))
    if initial<=0:
        raise ValueError("Material kg notoâgâri")
    old=await load_material_adjustment_summary(pool,load_id,material)
    oldp=Decimal(str(old["skidka_percent"] or 0))
    oldv=Decimal(str(old["vozvrat_kg"] or 0))
    if oldp+p>100:
        raise ValueError("Jami skidka foizi 100% dan oshmasligi kerak")
    # Vozvrat must not exceed kg left after cumulative skidka and previous return.
    final_after=(initial*(Decimal("1")-(oldp+p)/Decimal("100")))-(oldv+v)
    if final_after < 0:
        raise ValueError("Skidka va vozvrat jami material kgidan oshib ketadi")
    row=await pool.fetchrow("""
        INSERT INTO load_adjustments(load_id,material,skidka_percent,vozvrat_kg)
        VALUES($1,$2,$3,$4)
        RETURNING id
    """,load_id,material,p,v)
    return int(row["id"]), initial, oldp+p, oldv+v, final_after

async def load_adjustment_details(pool, load_id):
    rows=await pool.fetch("""
        SELECT material,
               COALESCE(SUM(skidka_percent),0) AS skidka_percent,
               COALESCE(SUM(vozvrat_kg),0) AS vozvrat_kg
        FROM load_adjustments
        WHERE load_id=$1
        GROUP BY material
        ORDER BY material
    """,load_id)
    return [dict(r) for r in rows]

async def recent_furnaces_for_adjustment(pool, limit=20):
    rows = await pool.fetch("""
        SELECT id, furnace_date, furnace_type, items, created_at
        FROM furnaces
        ORDER BY id DESC
        LIMIT $1
    """, limit)
    out=[]
    for r in rows:
        x=dict(r)
        if isinstance(x["items"], str):
            x["items"]=json.loads(x["items"])
        out.append(x)
    return out

async def furnace_materials_for_adjustment(pool, furnace_id):
    row=await pool.fetchrow("SELECT items FROM furnaces WHERE id=$1", furnace_id)
    if not row:
        return []
    items=row["items"] if isinstance(row["items"],list) else json.loads(row["items"])
    result=[]
    for x in items:
        name=str(x.get("material",""))
        kg=float(x.get("kg",0))
        if name and kg>0:
            result.append({"material":name,"kg":kg})
    return result

async def adjustment_details(pool, furnace_id):
    rows=await pool.fetch("""
        SELECT material,
               COALESCE(SUM(CASE WHEN adjustment_type='skidka' THEN kg ELSE 0 END),0) AS skidka_kg,
               COALESCE(SUM(CASE WHEN adjustment_type='vozvrat' THEN kg ELSE 0 END),0) AS vozvrat_kg
        FROM furnace_adjustments
        WHERE furnace_id=$1
        GROUP BY material
        ORDER BY material
    """, furnace_id)
    return [dict(r) for r in rows]

async def stock_summary(pool):
    rows = await pool.fetch("""
        WITH incoming AS (
            SELECT item->>'material' material,
                   SUM(COALESCE((item->>'accepted_kg')::numeric,(item->>'initial_kg')::numeric)) kg
            FROM loads l CROSS JOIN LATERAL jsonb_array_elements(l.items) item
            GROUP BY item->>'material'
        ), issued AS (
            SELECT item->>'material' material, SUM((item->>'kg')::numeric) kg
            FROM furnaces f CROSS JOIN LATERAL jsonb_array_elements(f.items) item
            GROUP BY item->>'material'
        ), finished AS (
            SELECT product material, SUM(kg) kg
            FROM finished_products
            GROUP BY product
        ), sold AS (
            SELECT product material, SUM(kg) kg FROM sales GROUP BY product
        )
        SELECT 'Xomashyo: '||COALESCE(i.material,o.material) material,
               COALESCE(i.kg,0)-COALESCE(o.kg,0) kg
        FROM incoming i FULL OUTER JOIN issued o ON o.material=i.material
        UNION ALL
        SELECT 'Tayyor: '||f.material material, f.kg-COALESCE(s.kg,0) kg
        FROM finished f LEFT JOIN sold s ON lower(s.material)=lower(f.material)
        ORDER BY material
    """)
    return rows

async def report(pool):
    incoming = await pool.fetchval("""
        SELECT COALESCE(SUM(COALESCE((item->>'accepted_kg')::numeric,(item->>'initial_kg')::numeric)),0)
        FROM loads l CROSS JOIN LATERAL jsonb_array_elements(l.items) item
    """)
    issued = await pool.fetchval("""
        SELECT COALESCE(SUM((item->>'kg')::numeric),0)
        FROM furnaces f CROSS JOIN LATERAL jsonb_array_elements(f.items) item
    """)
    finished = await pool.fetchval("SELECT COALESCE(SUM(kg),0) FROM finished_products")
    sold = await pool.fetchval("SELECT COALESCE(SUM(kg),0) FROM sales")
    revenue = await pool.fetchval("SELECT COALESCE(SUM(revenue),0) FROM sales")
    profit = await pool.fetchval("SELECT COALESCE(SUM(profit),0) FROM sales")
    return {"incoming_kg":incoming,"issued_kg":issued,"raw_stock_kg":incoming-issued,
            "finished_kg":finished,"sold_kg":sold,"revenue":revenue,
            "profit":max(profit,0),"loss":max(-profit,0)}

async def profit_loss(pool):
    return await pool.fetchval("SELECT COALESCE(SUM(profit),0) FROM sales")

async def close_pool(pool):
    await pool.close()
