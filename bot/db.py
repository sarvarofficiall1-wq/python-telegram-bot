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
    received_date DATE NOT NULL,
    vehicle_no TEXT NOT NULL,
    person_name TEXT NOT NULL,
    items JSONB NOT NULL,
    skidka_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    vozvrat_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

async def create_load(pool, received_date, vehicle_no, person_name, items, skidka_kg, vozvrat_kg):
    items_json = _json_items(items)
    total = sum(float(x["initial_kg"]) for x in items_json)
    deduction = float(skidka_kg) + float(vozvrat_kg)
    if total <= 0:
        raise ValueError("Yuk kg 0 dan katta boâlishi kerak")
    if deduction > total:
        raise ValueError("Skidka + vozvrat boshlangâich kg dan katta")
    for x in items_json:
        initial = float(x["initial_kg"])
        accepted = max(0.0, initial - deduction * initial / total)
        x["accepted_kg"] = str(round(accepted, 3))
    row = await pool.fetchrow("""
        INSERT INTO loads(received_date,vehicle_no,person_name,items,skidka_kg,vozvrat_kg)
        VALUES($1,$2,$3,$4::jsonb,$5,$6) RETURNING id
    """, received_date, vehicle_no, person_name, json.dumps(items_json, ensure_ascii=False),
       skidka_kg, vozvrat_kg)
    return int(row["id"])

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
