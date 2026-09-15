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

async def create_pool(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        dsn,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        command_timeout=COMMAND_TIMEOUT,
    )
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SCHEMA)
    logger.info("PostgreSQL pool ready.")
    return pool

async def upsert_user(pool, telegram_id, username, first_name):
    row = await pool.fetchrow(
        """
        INSERT INTO users (telegram_id, username, first_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_id) DO UPDATE
        SET username=EXCLUDED.username,
            first_name=EXCLUDED.first_name,
            last_seen=now()
        RETURNING (xmax = 0) AS is_new
        """,
        telegram_id, username, first_name
    )
    return bool(row["is_new"])

async def count_users(pool):
    return int(await pool.fetchval("SELECT count(*) FROM users"))

def _json_items(items):
    result = []
    for item in items:
        result.append({
            "material": str(item["material"]),
            "initial_kg": str(item["initial_kg"]),
            "price": str(item["price"]),
        })
    return result

async def create_load(pool, received_date, vehicle_no, person_name, items,
                      skidka_kg, vozvrat_kg):
    items_json = _json_items(items)
    total_kg = sum(float(x["initial_kg"]) for x in items_json)

    if total_kg <= 0:
        raise ValueError("Yuk kg 0 dan katta boâlishi kerak")

    total_deduction = float(skidka_kg) + float(vozvrat_kg)
    if total_deduction > total_kg:
        raise ValueError("Skidka + vozvrat boshlangâich kg dan katta")

    # Store accepted kg per material so warehouse calculations remain exact.
    for item in items_json:
        initial = float(item["initial_kg"])
        share = initial / total_kg
        deduction = total_deduction * share
        accepted = max(0.0, initial - deduction)
        item["accepted_kg"] = str(round(accepted, 3))

    row = await pool.fetchrow(
        """
        INSERT INTO loads
            (received_date, vehicle_no, person_name, items, skidka_kg, vozvrat_kg)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        RETURNING id
        """,
        received_date,
        vehicle_no,
        person_name,
        json.dumps(items_json, ensure_ascii=False),
        skidka_kg,
        vozvrat_kg,
    )
    return int(row["id"])

def _normalize_load(row):
    d = dict(row)
    if isinstance(d["items"], str):
        d["items"] = json.loads(d["items"])
    return d

async def get_load(pool, load_id):
    row = await pool.fetchrow(
        """
        SELECT id, received_date, vehicle_no, person_name, items,
               skidka_kg, vozvrat_kg, created_at
        FROM loads
        WHERE id=$1
        """,
        load_id
    )
    if not row:
        return None
    return _normalize_load(row)

async def search_loads(pool, text):
    q = f"%{text}%"
    rows = await pool.fetch(
        """
        SELECT id, received_date, vehicle_no, person_name, items,
               skidka_kg, vozvrat_kg, created_at
        FROM loads
        WHERE vehicle_no ILIKE $1 OR person_name ILIKE $1
        ORDER BY id DESC
        LIMIT 20
        """,
        q
    )
    return [_normalize_load(r) for r in rows]

async def create_furnace(pool, furnace_date, furnace_type, items,
                         finished_kg, scrap_kg):
    items_json = [
        {"material": str(x["material"]), "kg": str(x["kg"])}
        for x in items
    ]
    input_kg = sum(float(x["kg"]) for x in items_json)
    finished = float(finished_kg)
    scrap = float(scrap_kg)
    loss = input_kg - finished - scrap

    if input_kg <= 0:
        raise ValueError("Qozon kirimi 0 dan katta boâlishi kerak")
    if finished < 0 or scrap < 0 or loss < -0.0001:
        raise ValueError("Qozon balansi notoâgâri")

    # The current handler asks for product name, but passes it separately
    # only through the conversation state. It is intentionally kept as a
    # generic product label below; the handler's current create_furnace call
    # does not provide it, so an empty label is stored safely.
    row = await pool.fetchrow(
        """
        INSERT INTO furnaces
            (furnace_date, furnace_type, items, finished_product,
             finished_kg, scrap_kg, loss_kg)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)
        RETURNING id
        """,
        furnace_date,
        furnace_type,
        json.dumps(items_json, ensure_ascii=False),
        "",
        finished,
        scrap,
        loss,
    )
    return int(row["id"])

async def create_sale(pool, sale_date, product, kg, sale_price, cost_price):
    revenue = kg * sale_price
    profit = kg * (sale_price - cost_price)

    row = await pool.fetchrow(
        """
        INSERT INTO sales
            (sale_date, product, kg, sale_price, cost_price, revenue, profit)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        sale_date, product, kg, sale_price, cost_price, revenue, profit
    )
    return int(row["id"])

async def stock_summary(pool):
    rows = await pool.fetch(
        """
        WITH incoming AS (
            SELECT
                item->>'material' AS material,
                SUM(COALESCE((item->>'accepted_kg')::numeric,
                             (item->>'initial_kg')::numeric)) AS kg
            FROM loads l
            CROSS JOIN LATERAL jsonb_array_elements(l.items) item
            GROUP BY item->>'material'
        ),
        issued AS (
            SELECT
                item->>'material' AS material,
                SUM((item->>'kg')::numeric) AS kg
            FROM furnaces f
            CROSS JOIN LATERAL jsonb_array_elements(f.items) item
            GROUP BY item->>'material'
        )
        SELECT
            COALESCE(i.material, o.material) AS material,
            COALESCE(i.kg, 0) - COALESCE(o.kg, 0) AS kg
        FROM incoming i
        FULL OUTER JOIN issued o ON o.material=i.material
        ORDER BY material
        """
    )
    return rows

async def report(pool):
    incoming_kg = await pool.fetchval("""
        SELECT COALESCE(SUM(
            COALESCE((item->>'accepted_kg')::numeric,
                     (item->>'initial_kg')::numeric)
        ),0)
        FROM loads l
        CROSS JOIN LATERAL jsonb_array_elements(l.items) item
    """)

    issued_kg = await pool.fetchval("""
        SELECT COALESCE(SUM((item->>'kg')::numeric),0)
        FROM furnaces f
        CROSS JOIN LATERAL jsonb_array_elements(f.items) item
    """)

    finished_kg = await pool.fetchval(
        "SELECT COALESCE(SUM(finished_kg),0) FROM furnaces"
    )
    revenue = await pool.fetchval(
        "SELECT COALESCE(SUM(revenue),0) FROM sales"
    )
    profit = await pool.fetchval(
        "SELECT COALESCE(SUM(profit),0) FROM sales"
    )

    incoming_kg = incoming_kg or 0
    issued_kg = issued_kg or 0
    finished_kg = finished_kg or 0
    revenue = revenue or 0
    profit = profit or 0

    return {
        "incoming_kg": incoming_kg,
        "issued_kg": issued_kg,
        "raw_stock_kg": incoming_kg - issued_kg,
        "finished_kg": finished_kg,
        "revenue": revenue,
        "profit": max(profit, 0),
        "loss": max(-profit, 0),
    }

async def profit_loss(pool):
    return await pool.fetchval(
        "SELECT COALESCE(SUM(profit),0) FROM sales"
    )

async def close_pool(pool):
    await pool.close()
    logger.info("PostgreSQL pool closed.")
