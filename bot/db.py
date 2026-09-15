"""Zavod Hisob PostgreSQL layer."""
import json
import asyncpg

def fmt_kg(v):
    try:
        return f"{float(v):,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(v)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 telegram_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
 active_date DATE, active_date_confirmed BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_date DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_date_confirmed BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS loads(
 id BIGSERIAL PRIMARY KEY, load_no BIGINT, received_date DATE NOT NULL,
 vehicle_no TEXT NOT NULL, person_name TEXT NOT NULL, items JSONB NOT NULL,
 skidka_kg NUMERIC(18,3) NOT NULL DEFAULT 0, vozvrat_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE loads ADD COLUMN IF NOT EXISTS load_no BIGINT;
ALTER TABLE loads ADD COLUMN IF NOT EXISTS skidka_kg NUMERIC(18,3) NOT NULL DEFAULT 0;
ALTER TABLE loads ADD COLUMN IF NOT EXISTS vozvrat_kg NUMERIC(18,3) NOT NULL DEFAULT 0;
DROP INDEX IF EXISTS uq_loads_date_load_no;
CREATE UNIQUE INDEX IF NOT EXISTS uq_load_no_global ON loads(load_no);

CREATE TABLE IF NOT EXISTS furnaces(
 id BIGSERIAL PRIMARY KEY, furnace_date DATE NOT NULL, furnace_type TEXT NOT NULL,
 items JSONB NOT NULL, finished_product TEXT NOT NULL DEFAULT '',
 finished_kg NUMERIC(18,3) NOT NULL DEFAULT 0, scrap_kg NUMERIC(18,3) NOT NULL DEFAULT 0,
 loss_kg NUMERIC(18,3) NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE furnaces ADD COLUMN IF NOT EXISTS finished_product TEXT NOT NULL DEFAULT '';
ALTER TABLE furnaces ADD COLUMN IF NOT EXISTS finished_kg NUMERIC(18,3) NOT NULL DEFAULT 0;
ALTER TABLE furnaces ADD COLUMN IF NOT EXISTS scrap_kg NUMERIC(18,3) NOT NULL DEFAULT 0;
ALTER TABLE furnaces ADD COLUMN IF NOT EXISTS loss_kg NUMERIC(18,3) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS finished_products(
 id BIGSERIAL PRIMARY KEY, production_date DATE NOT NULL, product TEXT NOT NULL,
 kg NUMERIC(18,3) NOT NULL, furnace_id BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE finished_products ADD COLUMN IF NOT EXISTS furnace_id BIGINT;

CREATE TABLE IF NOT EXISTS sales(
 id BIGSERIAL PRIMARY KEY, sale_no BIGINT, sale_date DATE NOT NULL,
 buyer TEXT NOT NULL, items JSONB NOT NULL, revenue NUMERIC(24,2) NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sales ADD COLUMN IF NOT EXISTS sale_no BIGINT;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS buyer TEXT;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS items JSONB;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS revenue NUMERIC(24,2) NOT NULL DEFAULT 0;
DROP INDEX IF EXISTS idx_sales_date;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sale_no_global ON sales(sale_no);
CREATE INDEX IF NOT EXISTS idx_sales_date2 ON sales(sale_date);

CREATE TABLE IF NOT EXISTS expenses(
 id BIGSERIAL PRIMARY KEY, expense_no BIGINT, expense_date DATE NOT NULL,
 category TEXT NOT NULL, amount NUMERIC(24,2) NOT NULL, note TEXT DEFAULT '',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_no_global ON expenses(expense_no);

CREATE TABLE IF NOT EXISTS scrap_events(
 id BIGSERIAL PRIMARY KEY, event_no BIGINT, event_date DATE NOT NULL,
 scrap_type TEXT NOT NULL, kg NUMERIC(18,3) NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('produce','sale','use','discard')),
 unit_price NUMERIC(20,2) NOT NULL DEFAULT 0, buyer TEXT DEFAULT '',
 destination TEXT DEFAULT '', note TEXT DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scrap_event_no_global ON scrap_events(event_no);

CREATE INDEX IF NOT EXISTS idx_loads_date2 ON loads(received_date);
CREATE INDEX IF NOT EXISTS idx_loads_vehicle2 ON loads(vehicle_no);
CREATE INDEX IF NOT EXISTS idx_loads_person2 ON loads(person_name);
CREATE INDEX IF NOT EXISTS idx_furnaces_date2 ON furnaces(furnace_date);
CREATE INDEX IF NOT EXISTS idx_finished_date2 ON finished_products(production_date);
"""

async def create_pool(dsn):
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, command_timeout=20)
    async with pool.acquire() as c:
        await c.execute(SCHEMA)
        # Give legacy rows numbers if they do not have one.
        await c.execute("""WITH x AS (
          SELECT id, ROW_NUMBER() OVER (ORDER BY id) rn FROM loads WHERE load_no IS NULL
        ) UPDATE loads l SET load_no=x.rn FROM x WHERE l.id=x.id""")
        await c.execute("""WITH x AS (
          SELECT id, ROW_NUMBER() OVER (ORDER BY id) rn FROM sales WHERE sale_no IS NULL
        ) UPDATE sales s SET sale_no=x.rn FROM x WHERE s.id=x.id""")
        await c.execute("""WITH x AS (
          SELECT id, ROW_NUMBER() OVER (ORDER BY id) rn FROM expenses WHERE expense_no IS NULL
        ) UPDATE expenses e SET expense_no=x.rn FROM x WHERE e.id=x.id""")
        await c.execute("""WITH x AS (
          SELECT id, ROW_NUMBER() OVER (ORDER BY id) rn FROM scrap_events WHERE event_no IS NULL
        ) UPDATE scrap_events s SET event_no=x.rn FROM x WHERE s.id=x.id""")
    return pool

async def close_pool(pool): await pool.close()

async def upsert_user(pool, telegram_id, username, first_name):
    await pool.execute("""INSERT INTO users(telegram_id,username,first_name,last_seen)
    VALUES($1,$2,$3,now()) ON CONFLICT(telegram_id) DO UPDATE
    SET username=$2,first_name=$3,last_seen=now()""",telegram_id,username,first_name)

async def get_active_date(pool, telegram_id, today):
    r=await pool.fetchrow("SELECT active_date,active_date_confirmed FROM users WHERE telegram_id=$1",telegram_id)
    return r["active_date"] if r and r["active_date"]==today and r["active_date_confirmed"] else None

async def set_active_date(pool, telegram_id, d):
    await pool.execute("UPDATE users SET active_date=$2,active_date_confirmed=TRUE,last_seen=now() WHERE telegram_id=$1",telegram_id,d)

def _load_items(items):
    return items if isinstance(items,list) else json.loads(items)

async def create_load(pool,d,vehicle,person,items):
    async with pool.acquire() as c, c.transaction():
        no=await c.fetchval("SELECT COALESCE(MAX(load_no),0)+1 FROM loads")
        clean=[{"material":str(x["material"]),"kg":str(x["kg"]),"price":str(x["price"]),
                "skidka_pct":str(x.get("skidka_pct",0)),"vozvrat_kg":str(x.get("vozvrat_kg",0))}
               for x in items]
        row=await c.fetchrow("""INSERT INTO loads(load_no,received_date,vehicle_no,person_name,items)
        VALUES($1,$2,$3,$4,$5::jsonb) RETURNING id,load_no""",no,d,vehicle,person,json.dumps(clean,ensure_ascii=False))
        return int(row["id"]),int(row["load_no"])

async def daily_load_total(pool,d):
    r=await pool.fetchrow("""SELECT COUNT(*) n,COALESCE(SUM(
      (SELECT COALESCE(SUM((x->>'kg')::numeric),0) FROM jsonb_array_elements(items)x)),0) kg
      FROM loads WHERE received_date=$1""",d)
    return float(r["kg"]),int(r["n"])

async def raw_stock(pool):
    r=await pool.fetch("""SELECT material,COALESCE(SUM(q),0) kg FROM (
      SELECT x->>'material' material,(x->>'kg')::numeric q FROM loads l,jsonb_array_elements(l.items)x
      UNION ALL
      SELECT x->>'material',-((x->>'kg')::numeric) FROM furnaces f,jsonb_array_elements(f.items)x
    )z GROUP BY material ORDER BY material""")
    return [{"material":x["material"],"kg":float(x["kg"])} for x in r if float(x["kg"])>.0001]

async def material_stock(pool,material):
    r=await pool.fetchval("""SELECT COALESCE(SUM(q),0) FROM (
      SELECT (x->>'kg')::numeric q FROM loads l,jsonb_array_elements(l.items)x WHERE lower(x->>'material')=lower($1)
      UNION ALL
      SELECT -((x->>'kg')::numeric) FROM furnaces f,jsonb_array_elements(f.items)x WHERE lower(x->>'material')=lower($1)
    )z""",material)
    return float(r or 0)

async def create_furnace(pool,d,kind,items):
    async with pool.acquire() as c,c.transaction():
        for x in items:
            r=await c.fetchval("""SELECT COALESCE(SUM(q),0) FROM (
              SELECT (x->>'kg')::numeric q FROM loads l,jsonb_array_elements(l.items)x WHERE lower(x->>'material')=lower($1)
              UNION ALL
              SELECT -((x->>'kg')::numeric) FROM furnaces f,jsonb_array_elements(f.items)x WHERE lower(x->>'material')=lower($1)
            )z""",x["material"])
            if float(x["kg"])>float(r or 0)+.0001:
                raise ValueError(f"{x['material']} omborda yetarli emas. Qoldiq: {fmt_kg(r)} kg")
        row=await c.fetchrow("""INSERT INTO furnaces(furnace_date,furnace_type,items)
          VALUES($1,$2,$3::jsonb) RETURNING id""",d,kind,json.dumps([{"material":x["material"],"kg":str(x["kg"])} for x in items],ensure_ascii=False))
        return int(row["id"])

async def furnace_list(pool,kind=None):
    q="SELECT * FROM furnaces"
    args=[]
    if kind:q+=" WHERE furnace_type=$1";args=[kind]
    q+=" ORDER BY id DESC LIMIT 50"
    return await pool.fetch(q,*args)

async def create_output(pool,d,furnace_id,product,kgv):
    r=await pool.fetchrow("SELECT furnace_type FROM furnaces WHERE id=$1",furnace_id)
    if not r: raise ValueError("Qozon raqami topilmadi")
    await pool.execute("""INSERT INTO finished_products(production_date,product,kg,furnace_id)
      VALUES($1,$2,$3,$4)""",d,product,kgv,furnace_id)

async def finished_stock(pool):
    r=await pool.fetch("""SELECT product,COALESCE(SUM(q),0) kg FROM (
      SELECT product,kg q FROM finished_products
      UNION ALL
      SELECT x->>'product',-((x->>'kg')::numeric) FROM sales s,jsonb_array_elements(s.items)x
    )z GROUP BY product ORDER BY product""")
    return [{"product":x["product"],"kg":float(x["kg"])} for x in r if float(x["kg"])>.0001]

async def finished_stock_one(pool,product):
    r=await pool.fetchval("""SELECT COALESCE(SUM(q),0) FROM (
      SELECT kg q FROM finished_products WHERE lower(product)=lower($1)
      UNION ALL
      SELECT -((x->>'kg')::numeric) FROM sales s,jsonb_array_elements(s.items)x
      WHERE lower(x->>'product')=lower($1)
    )z""",product)
    return float(r or 0)

async def create_sale(pool,d,buyer,items):
    for x in items:
        av=await finished_stock_one(pool,x["product"])
        if float(x["kg"])>av+.0001: raise ValueError(f"{x['product']} qoldigâi {fmt_kg(av)} kg")
    rev=sum(float(x["kg"])*float(x["price"]) for x in items)
    async with pool.acquire() as c,c.transaction():
        no=await c.fetchval("SELECT COALESCE(MAX(sale_no),0)+1 FROM sales")
        row=await c.fetchrow("""INSERT INTO sales(sale_no,sale_date,buyer,items,revenue)
        VALUES($1,$2,$3,$4::jsonb,$5) RETURNING sale_no""",no,d,buyer,json.dumps(items,ensure_ascii=False),rev)
        return int(row["sale_no"]),rev

async def create_expense(pool,d,category,amount,note=""):
    async with pool.acquire() as c,c.transaction():
        no=await c.fetchval("SELECT COALESCE(MAX(expense_no),0)+1 FROM expenses")
        await c.execute("INSERT INTO expenses(expense_no,expense_date,category,amount,note) VALUES($1,$2,$3,$4,$5)",no,d,category,amount,note)
        return int(no)

async def scrap_stock_one(pool,stype):
    r=await pool.fetchval("""SELECT COALESCE(SUM(CASE WHEN action='produce' THEN kg ELSE -kg END),0)
      FROM scrap_events WHERE lower(scrap_type)=lower($1)""",stype)
    return float(r or 0)

async def scrap_stock(pool):
    r=await pool.fetch("""SELECT scrap_type,SUM(CASE WHEN action='produce' THEN kg ELSE -kg END) kg
      FROM scrap_events GROUP BY scrap_type ORDER BY scrap_type""")
    return [{"scrap_type":x["scrap_type"],"kg":float(x["kg"])} for x in r if float(x["kg"])>.0001]

async def create_scrap(pool,d,stype,kgv,action,price=0,buyer="",destination="",note=""):
    if action!="produce":
        av=await scrap_stock_one(pool,stype)
        if float(kgv)>av+.0001: raise ValueError(f"{stype} qoldigâi {fmt_kg(av)} kg")
    async with pool.acquire() as c,c.transaction():
        no=await c.fetchval("SELECT COALESCE(MAX(event_no),0)+1 FROM scrap_events")
        await c.execute("""INSERT INTO scrap_events(event_no,event_date,scrap_type,kg,action,unit_price,buyer,destination,note)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",no,d,stype,kgv,action,price,buyer,destination,note)
        return int(no)

async def report(pool,d1,d2):
    r=await pool.fetchrow("""SELECT COUNT(*) n,COALESCE(SUM((SELECT COALESCE(SUM((x->>'kg')::numeric),0)
      FROM jsonb_array_elements(items)x)),0) kg FROM loads WHERE received_date BETWEEN $1 AND $2""",d1,d2)
    s=await pool.fetchrow("SELECT COUNT(*) n,COALESCE(SUM(revenue),0) rev FROM sales WHERE sale_date BETWEEN $1 AND $2",d1,d2)
    e=await pool.fetchrow("SELECT COALESCE(SUM(amount),0) amount FROM expenses WHERE expense_date BETWEEN $1 AND $2",d1,d2)
    return {"loads":int(r["n"]),"incoming_kg":float(r["kg"]),"sales":int(s["n"]),"revenue":float(s["rev"]),"expenses":float(e["amount"])}
