"""Factory accounting Telegram handlers."""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from bot import db

logger = logging.getLogger(__name__)
DB_KEY="db"; REDIS_KEY="redis"
ADD_LOAD="➕ Yuk qabul qilish"; COPPER="🔥 Mis qozon"; BRASS="🔥 Latun qozon"; ALUMINUM="🔥 Alyumin qozon"
SALE="💰 Sotuv"; STOCK="📦 Ombor"; FINISHED="🏭 Tayyor mahsulot"; REPORT="📊 Hisobot"; SEARCH="🔎 Qidirish"; PROFIT="🟢 Foyda"; LOSS="🔴 Zarar"
EDIT="✏️ O‘zgartirish"; ADJUST="⬇️ Yuk skidka / ↩️ Vozvrat"; CANCEL="🚫 Bekor qilish"
LOAD_MATERIALS=['Qizil oddiy', 'Tros', 'Qizil lahim', 'Sariq', 'Radiator Sariq', 'Radiator qizil', 'Quyma sink', 'Karbyurator', 'Teplo', 'Alyumin zapchast', 'Alyumin chushka', 'Qizil skidka']
MAIN_KEYBOARD=[[ADD_LOAD],[COPPER,BRASS],[ALUMINUM,SALE],[FINISHED,STOCK],[REPORT,SEARCH],[PROFIT,LOSS],[ADJUST,EDIT]]
FURNACE_MATERIALS={"mis":["Qizil","Qizil lahim","Tros"],
"latun":["Sariq","Karbyurator","Radiator Qizil","Radiator Sariq","Sink"],
"alyumin":["Alyumin zapchast","Alyumin chushka"]}

LOAD_CONFIRM,LOAD_DATE,LOAD_VEHICLE,LOAD_PERSON,LOAD_MATERIAL,LOAD_KG,LOAD_PRICE,LOAD_MORE,LOAD_CUSTOM=range(9)
F_DATE,F_MATERIAL,F_KG,F_MORE,F_SCRAP,F_CUSTOM,F_ADJ_CONFIRM,F_ADJ_MATERIAL,F_ADJ_TYPE,F_ADJ_KG,F_ADJ_MORE=range(10,21)
S_PRODUCT,S_KG,S_PRICE,S_COST=range(17,21)
EDIT_TYPE,EDIT_ID,EDIT_MATERIAL,EDIT_KG,EDIT_FINISHED,EDIT_SCRAP=range(21,27)
SEARCH_TEXT=27
ADJ_FURNACE,ADJ_MATERIAL,ADJ_TYPE,ADJ_KG,ADJ_MORE=range(28,33)
LOADADJ_SEARCH,LOADADJ_LOAD,LOADADJ_MATERIAL,LOADADJ_SKIDKA_PCT,LOADADJ_VOZVRAT_KG=range(40,45)

def menu_markup(): return ReplyKeyboardMarkup(MAIN_KEYBOARD,resize_keyboard=True)
def cancel_markup(): return ReplyKeyboardMarkup([[CANCEL]],resize_keyboard=True)
def parse_decimal(t):
    try:
        v=Decimal(t.replace(" ","").replace(",","."))
        return v if v>=0 else None
    except (InvalidOperation,ValueError): return None
def pool_from(c): return c.application.bot_data.get(DB_KEY)

async def start(update,context):
    pool=pool_from(context)
    if pool:
        u=update.effective_user
        await db.upsert_user(pool,u.id,u.username,u.first_name)
    await update.message.reply_text("🏭 Zavod Hisob botiga xush kelibsiz!\n\nYuk, qozon, ombor, sotuv, foyda va zarar hisoblanadi.",reply_markup=menu_markup())

async def help_command(update,context):
    await update.message.reply_text("Menyudan kerakli bo‘limni tanlang. ❌ Bekor qilish bilan joriy amal to‘xtaydi.",reply_markup=menu_markup())
async def cancel(update,context):
    context.user_data.clear(); await update.message.reply_text("Bekor qilindi.",reply_markup=menu_markup()); return ConversationHandler.END
async def set_bot_commands(application):
    await application.bot.set_my_commands([("start","Asosiy menyu"),("help","Yordam"),("cancel","Bekor qilish")])

def load_material_markup():
    buttons = [[x] for x in LOAD_MATERIALS]
    buttons.append(["➕ Boshqa material"])
    buttons.append([CANCEL])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def load_start(update,context):
    pool=pool_from(context); u=update.effective_user; today=date.today()
    context.user_data["load"]={"items":[]}
    active=await db.get_active_date(pool,u.id,today) if pool else None
    if active:
        context.user_data["load"]["date"]=active
        await update.message.reply_text(f"📅 Sana: {active.strftime('%d.%m.%Y')} (bugun uchun tasdiqlangan).\n🚚 Mashina raqamini kiriting:",reply_markup=cancel_markup())
        return LOAD_VEHICLE
    await update.message.reply_text(f"📅 Bugungi sana {today.strftime('%d.%m.%Y')}.\nShu sana bilan davom etamizmi?",reply_markup=ReplyKeyboardMarkup([["✅ Ha","📅 Boshqa sana"],[CANCEL]],resize_keyboard=True))
    return LOAD_CONFIRM

async def load_confirm(update,context):
    t=update.message.text
    if t=="✅ Ha":
        d=date.today(); context.user_data["load"]["date"]=d
        pool=pool_from(context)
        if pool: await db.set_active_date(pool,update.effective_user.id,d)
        await update.message.reply_text("🚚 Mashina raqamini kiriting:"); return LOAD_VEHICLE
    if t=="📅 Boshqa sana":
        await update.message.reply_text("Sanani kiriting. Masalan: 14.09.2026"); return LOAD_DATE
    await update.message.reply_text("✅ Ha yoki 📅 Boshqa sana ni tanlang."); return LOAD_CONFIRM

async def load_date(update,context):
    try:
        d,m,y=map(int,update.message.text.strip().split(".")); d=date(y,m,d)
    except Exception:
        await update.message.reply_text("Sana noto‘g‘ri. Masalan: 15.09.2026"); return LOAD_DATE
    context.user_data["load"]["date"]=d
    pool=pool_from(context)
    if pool: await db.set_active_date(pool,update.effective_user.id,d)
    await update.message.reply_text("🚚 Mashina raqamini kiriting:"); return LOAD_VEHICLE
async def load_vehicle(update,context):
    context.user_data["load"]["vehicle"]=update.message.text.strip(); await update.message.reply_text("👤 Haydovchi / shaxs ismini kiriting:"); return LOAD_PERSON
async def load_person(update,context):
    context.user_data["load"]["person"]=update.message.text.strip(); await update.message.reply_text("📦 Materialni tanlang:",reply_markup=load_material_markup()); return LOAD_MATERIAL
async def load_material(update,context):
    name=update.message.text.strip()
    if name=="➕ Boshqa material":
        await update.message.reply_text("📦 Boshqa material nomini kiriting:",reply_markup=cancel_markup())
        return LOAD_CUSTOM
    if name not in LOAD_MATERIALS:
        await update.message.reply_text("Iltimos, materialni tugmadan tanlang.",reply_markup=load_material_markup())
        return LOAD_MATERIAL
    context.user_data["load"]["current_material"]=name
    await update.message.reply_text("⚖️ Shu materialning boshlang‘ich kg miqdorini kiriting:",reply_markup=cancel_markup())
    return LOAD_KG

async def load_custom(update,context):
    name=update.message.text.strip()
    if not name:
        await update.message.reply_text("Material nomini kiriting.")
        return LOAD_CUSTOM
    context.user_data["load"]["current_material"]=name
    await update.message.reply_text("⚖️ Shu materialning boshlang‘ich kg miqdorini kiriting:",reply_markup=cancel_markup())
    return LOAD_KG
async def load_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0: await update.message.reply_text("Kg noto‘g‘ri. Masalan: 3000"); return LOAD_KG
    context.user_data["load"]["current_kg"]=v; await update.message.reply_text("💵 1 kg narxini kiriting:"); return LOAD_PRICE
async def load_price(update,context):
    v=parse_decimal(update.message.text)
    if v is None: await update.message.reply_text("Narx noto‘g‘ri."); return LOAD_PRICE
    d=context.user_data["load"]; d["items"].append({"material":d.pop("current_material"),"initial_kg":d.pop("current_kg"),"price":v})
    await update.message.reply_text("Yana boshqa material qo‘shasiz?",reply_markup=ReplyKeyboardMarkup([["✅ Ha","❌ Yo‘q"],[CANCEL]],resize_keyboard=True)); return LOAD_MORE
async def load_more(update,context):
    if update.message.text=="✅ Ha":
        await update.message.reply_text("📦 Keyingi materialni tanlang:",reply_markup=load_material_markup())
        return LOAD_MATERIAL
    if update.message.text=="✅ Yo‘q":
        d=context.user_data["load"]; pool=pool_from(context)
        try:
            result=await db.create_load(pool,d["date"],d["vehicle"],d["person"],d["items"],0,0)
            lid, load_no = result
        except Exception as e:
            await update.message.reply_text(f"❌ Saqlashda xato: {e}",reply_markup=menu_markup())
            context.user_data.clear()
            return ConversationHandler.END
        initial=sum(x["initial_kg"] for x in d["items"])
        total_kg, load_count = await db.daily_load_total(pool, d["date"])
        total_ton = total_kg / 1000
        await update.message.reply_text(
            f"✅ Yuk #{load_no} saqlandi.\n"
            f"🚚 {d['vehicle']} | 👤 {d['person']}\n"
            f"⚖️ Kirim: {fmt_kg(initial)} kg\n\n"
            f"📅 {d['date'].strftime('%d.%m.%Y')} jami:\n"
            f"🚛 Yuklar: {load_count} ta\n"
            f"⚖️ Jami: {fmt_kg(total_kg)} kg ({total_ton:.3f} tonna)",
            reply_markup=menu_markup()
        )
        context.user_data.clear()
        return ConversationHandler.END
    await update.message.reply_text("✅ Ha yoki ❌ Yo‘q ni tanlang."); return LOAD_MORE

def furnace_material_markup(kind):
    buttons = [[x] for x in FURNACE_MATERIALS[kind]]
    buttons.append(["➕ Boshqa material"])
    buttons.append([CANCEL])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def furnace_start_factory(kind,title):
    async def fn(update,context):
        context.user_data["furnace"]={"kind":kind,"items":[],"date":date.today()}
        await update.message.reply_text(
            f"{title}\n📅 Sana avtomatik: {date.today().strftime('%d.%m.%Y')}\n"
            "📦 Qozonga beriladigan mahsulot turini tanlang:",
            reply_markup=furnace_material_markup(kind)
        )
        return F_MATERIAL
    return fn

async def furnace_material(update,context):
    d=context.user_data["furnace"]; name=update.message.text.strip()
    if name == "➕ Boshqa material":
        await update.message.reply_text(
            "✍️ Mahsulot turining nomini yozing:",
            reply_markup=cancel_markup()
        )
        return F_CUSTOM
    if name not in FURNACE_MATERIALS[d["kind"]]:
        await update.message.reply_text(
            "Iltimos, quyidagi variantlardan birini tanlang:",
            reply_markup=furnace_material_markup(d["kind"])
        )
        return F_MATERIAL
    d["current_material"]=name
    await update.message.reply_text("⚖️ Necha kg qozonga berildi?", reply_markup=cancel_markup())
    return F_KG

async def furnace_custom(update,context):
    name=update.message.text.strip()
    if not name:
        await update.message.reply_text("Mahsulot nomini yozing:")
        return F_CUSTOM
    context.user_data["furnace"]["current_material"]=name
    await update.message.reply_text("⚖️ Necha kg qozonga berildi?", reply_markup=cancel_markup())
    return F_KG
async def furnace_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0: await update.message.reply_text("Kg noto‘g‘ri."); return F_KG
    d=context.user_data["furnace"]; d["items"].append({"material":d.pop("current_material"),"kg":v})
    await update.message.reply_text("Yana material qo‘shasiz?",reply_markup=ReplyKeyboardMarkup([["✅ Ha","❌ Yo‘q"],[CANCEL]],resize_keyboard=True)); return F_MORE
async def furnace_more(update,context):
    if update.message.text=="✅ Ha":
        d=context.user_data["furnace"]
        await update.message.reply_text("📦 Keyingi materialni tanlang:", reply_markup=furnace_material_markup(d["kind"]))
        return F_MATERIAL
    if update.message.text=="✅ Yo‘q":
        await update.message.reply_text("♻️ Chiqit necha kg chiqdi?", reply_markup=cancel_markup())
        return F_SCRAP
    await update.message.reply_text("✅ Ha yoki ❌ Yo‘q ni tanlang.")
    return F_MORE

async def furnace_scrap(update,context):
    v=parse_decimal(update.message.text)
    d=context.user_data["furnace"]; pool=pool_from(context)
    if v is None:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return F_SCRAP
    inp=sum(x["kg"] for x in d["items"])
    loss=inp-v
    if loss<0:
        await update.message.reply_text("❌ Chiqit qozon kirimidan katta.")
        return F_SCRAP
    try:
        fid=await db.create_furnace(
            pool, d.get("date",date.today()), d["kind"], d["items"], "", 0, v
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Saqlashda xato: {e}",reply_markup=menu_markup())
        context.user_data.clear()
        return ConversationHandler.END

    d["furnace_id"]=fid
    d["adjustments"]=[]
    await update.message.reply_text(
        f"✅ Qozon #{fid} saqlandi.\n"
        f"📦 Material kirimi: {fmt_kg(inp)} kg\n"
        f"♻️ Chiqit: {fmt_kg(v)} kg\n"
        f"🔻 Jarayon yo‘qotishi: {fmt_kg(loss)} kg ({loss/inp*100:.2f}%)\n\n"
        "⬇️ Skidka/vozvratni keyin ham istalgan vaqtda "
        "«⬇️ Skidka / ↩️ Vozvrat» bo‘limidan kiritishingiz mumkin.",
        reply_markup=menu_markup()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def furnace_adjust_confirm(update,context):
    t=update.message.text
    if t=="✅ Ha":
        items=context.user_data["furnace"]["items"]
        names=[]
        for x in items:
            if x["material"] not in names:
                names.append(x["material"])
        context.user_data["furnace"]["adjust_materials"]=names
        await update.message.reply_text(
            "📦 Skidka/vozvrat qaysi materialga tegishli?",
            reply_markup=ReplyKeyboardMarkup([[x] for x in names]+[[CANCEL]],resize_keyboard=True)
        )
        return F_ADJ_MATERIAL
    if t=="❌ Yo‘q":
        context.user_data.clear()
        await update.message.reply_text("✅ Qozon yakunlandi.",reply_markup=menu_markup())
        return ConversationHandler.END
    await update.message.reply_text("✅ Ha yoki ❌ Yo‘q ni tanlang.")
    return F_ADJ_CONFIRM

async def furnace_adjust_material(update,context):
    name=update.message.text.strip()
    names=context.user_data["furnace"].get("adjust_materials",[])
    if name not in names:
        await update.message.reply_text("Iltimos, materialni tugmadan tanlang.")
        return F_ADJ_MATERIAL
    context.user_data["furnace"]["adjust_material"]=name
    await update.message.reply_text(
        "⬇️ Qaysi biri?",
        reply_markup=ReplyKeyboardMarkup([["⬇️ Skidka","↩️ Vozvrat"],[CANCEL]],resize_keyboard=True)
    )
    return F_ADJ_TYPE

async def furnace_adjust_type(update,context):
    mp={"⬇️ Skidka":"skidka","↩️ Vozvrat":"vozvrat"}
    t=mp.get(update.message.text)
    if not t:
        await update.message.reply_text("⬇️ Skidka yoki ↩️ Vozvrat ni tanlang.")
        return F_ADJ_TYPE
    context.user_data["furnace"]["adjust_type"]=t
    await update.message.reply_text("⚖️ Necha kg?",reply_markup=cancel_markup())
    return F_ADJ_KG

async def furnace_adjust_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0:
        await update.message.reply_text("Kg noto‘g‘ri. Masalan: 5")
        return F_ADJ_KG
    d=context.user_data["furnace"]; pool=pool_from(context)
    try:
        aid=await db.create_furnace_adjustment(
            pool,d["furnace_id"],d["adjust_material"],d["adjust_type"],v
        )
        rows=await db.get_furnace_adjustments(pool,d["furnace_id"])
        last=next(r for r in rows if int(r["id"])==aid)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}",reply_markup=menu_markup())
        context.user_data.clear()
        return ConversationHandler.END

    typ="Skidka" if d["adjust_type"]=="skidka" else "Vozvrat"
    await update.message.reply_text(
        f"✅ {typ}: {fmt_kg(v)} kg\n"
        f"📦 Material: {d['adjust_material']}\n"
        f"📊 Foiz: {float(last['percent']):.2f}%\n\n"
        "Yana skidka/vozvrat kiritasizmi?",
        reply_markup=ReplyKeyboardMarkup([["✅ Ha","❌ Yo‘q"],[CANCEL]],resize_keyboard=True)
    )
    return F_ADJ_MORE

async def furnace_adjust_more(update,context):
    t=update.message.text
    if t=="✅ Ha":
        names=context.user_data["furnace"].get("adjust_materials",[])
        await update.message.reply_text(
            "📦 Materialni tanlang:",
            reply_markup=ReplyKeyboardMarkup([[x] for x in names]+[[CANCEL]],resize_keyboard=True)
        )
        return F_ADJ_MATERIAL
    if t=="❌ Yo‘q":
        context.user_data.clear()
        await update.message.reply_text("✅ Qozon va skidka/vozvrat ma’lumotlari saqlandi.",reply_markup=menu_markup())
        return ConversationHandler.END
    await update.message.reply_text("✅ Ha yoki ❌ Yo‘q ni tanlang.")
    return F_ADJ_MORE




async def load_adjust_start(update,context):
    await update.message.reply_text(
        "⬇️ Yuk skidka / ↩️ Vozvrat\n\n"
        "Yukni topish uchun quyidagilardan birini yozing:\n"
        "📅 Sana: 15.09.2026\n"
        "👤 Ism/familiya\n"
        "🚚 Mashina raqami\n"
        "⚖️ Kg: 1000",
        reply_markup=ReplyKeyboardMarkup([[CANCEL]],resize_keyboard=True)
    )
    return LOADADJ_SEARCH

async def load_adjust_search(update,context):
    q=update.message.text.strip()
    rows=await db.search_loads_for_adjustment(pool_from(context),q)
    if not rows:
        await update.message.reply_text(
            "❌ Yuk topilmadi.\n"
            "Sana, ism, mashina raqami yoki kg ni tekshirib qayta kiriting.",
            reply_markup=ReplyKeyboardMarkup([[CANCEL]],resize_keyboard=True)
        )
        return LOADADJ_SEARCH
    context.user_data["load_adj_loads"]=rows
    buttons=[]
    for x in rows:
        total=sum(float(i.get("initial_kg",0)) for i in x["items"])
        buttons.append([f"#{x.get('load_no') or x['id']} | {x['person_name']} | {fmt_kg(total)} kg"])
    buttons.append([CANCEL])
    await update.message.reply_text(
        "🚚 Topilgan yuklardan keraklisini tanlang:",
        reply_markup=ReplyKeyboardMarkup(buttons,resize_keyboard=True)
    )
    return LOADADJ_LOAD

async def load_adjust_load(update,context):
    text=update.message.text.strip()
    rows=context.user_data.get("load_adj_loads",[])
    selected=None
    for x in rows:
        total=sum(float(i.get("initial_kg",0)) for i in x["items"])
        label=f"#{x.get('load_no') or x['id']} | {x['person_name']} | {fmt_kg(total)} kg"
        if text==label:
            selected=x; break
    if not selected:
        await update.message.reply_text("Yukni tugmadan tanlang.")
        return LOADADJ_LOAD
    context.user_data["load_adj_load"]=selected
    buttons=[[f"{i['material']} — {fmt_kg(i['initial_kg'])} kg"] for i in selected["items"]]
    buttons.append([CANCEL])
    await update.message.reply_text(
        f"🚚 Yuk #{selected.get('load_no') or selected['id']}\n"
        f"📅 {selected['received_date'].strftime('%d.%m.%Y')}\n"
        f"👤 {selected['person_name']}\n"
        "📦 Materialni tanlang:",
        reply_markup=ReplyKeyboardMarkup(buttons,resize_keyboard=True)
    )
    return LOADADJ_MATERIAL

async def load_adjust_material(update,context):
    text=update.message.text.strip()
    selected=context.user_data["load_adj_load"]
    item=None
    for i in selected["items"]:
        if text==f"{i['material']} — {fmt_kg(i['initial_kg'])} kg":
            item=i; break
    if not item:
        await update.message.reply_text("Materialni tugmadan tanlang.")
        return LOADADJ_MATERIAL
    context.user_data["load_adj_material"]=item["material"]
    summary=await db.load_material_adjustment_summary(
        pool_from(context),selected["id"],item["material"]
    )
    old_pct=float(summary["skidka_percent"] or 0)
    old_v=float(summary["vozvrat_kg"] or 0)
    await update.message.reply_text(
        f"📦 {item['material']}\n"
        f"⚖️ Kelgan: {fmt_kg(item['initial_kg'])} kg\n"
        f"⬇️ Hozirgi skidka: {old_pct:.2f}%\n"
        f"↩️ Hozirgi vozvrat: {fmt_kg(old_v)} kg\n\n"
        "📊 Yangi skidka foizini kiriting.\n"
        "Ayrilmasa: 0",
        reply_markup=cancel_markup()
    )
    return LOADADJ_SKIDKA_PCT

async def load_adjust_skidka_pct(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<0 or v>100:
        await update.message.reply_text("Foiz 0–100 oralig‘ida bo‘lishi kerak. Masalan: 2.5")
        return LOADADJ_SKIDKA_PCT
    context.user_data["load_adj_skidka_pct"]=v
    await update.message.reply_text(
        "↩️ Yangi vozvrat kg ni kiriting.\n"
        "Ayrilmasa: 0",
        reply_markup=cancel_markup()
    )
    return LOADADJ_VOZVRAT_KG

async def load_adjust_vozvrat_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<0:
        await update.message.reply_text("Kg noto‘g‘ri. Masalan: 10")
        return LOADADJ_VOZVRAT_KG
    d=context.user_data
    try:
        initial,skidka_kg,vozvrat,final=await db.set_load_material_adjustment(
            pool_from(context),d["load_adj_load"]["id"],d["load_adj_material"],
            d["load_adj_skidka_pct"],v
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {e}",reply_markup=menu_markup())
        context.user_data.clear()
        return ConversationHandler.END
    await update.message.reply_text(
        f"✅ O‘zgartirildi.\n"
        f"📦 {d['load_adj_material']}\n"
        f"⚖️ Kelgan: {fmt_kg(initial)} kg\n"
        f"⬇️ Skidka: {float(d['load_adj_skidka_pct']):.2f}% = {fmt_kg(skidka_kg)} kg\n"
        f"↩️ Vozvrat: {fmt_kg(vozvrat)} kg\n"
        f"📦 Qolgan/qabul: {fmt_kg(final)} kg",
        reply_markup=menu_markup()
    )
    context.user_data.clear()
    return ConversationHandler.END


def adjust_furnace_markup(rows):
    buttons=[]
    for r in rows:
        typ={"mis":"Mis","latun":"Latun","alyumin":"Alyumin"}.get(r["furnace_type"],r["furnace_type"])
        buttons.append([f"#{r['id']} | {typ} | {r['furnace_date'].strftime('%d.%m.%Y')}"])
    buttons.append([CANCEL])
    return ReplyKeyboardMarkup(buttons,resize_keyboard=True)

async def adjust_start(update,context):
    pool=pool_from(context)
    rows=await db.recent_furnaces_for_adjustment(pool,30)
    if not rows:
        await update.message.reply_text("Hali qozonlar ro‘yxatga olinmagan.",reply_markup=menu_markup())
        return ConversationHandler.END
    context.user_data["adjust_rows"]=rows
    await update.message.reply_text(
        "⬇️ Skidka / ↩️ Vozvrat\n"
        "Qaysi qozondagi materialga o‘zgartirish kiritasiz?\n"
        "Qozon raqamini tanlang:",
        reply_markup=adjust_furnace_markup(rows)
    )
    return ADJ_FURNACE

async def adjust_furnace(update,context):
    text=update.message.text.strip()
    if not text.startswith("#"):
        await update.message.reply_text("Qozonni tugmadan tanlang.")
        return ADJ_FURNACE
    try:
        furnace_id=int(text.split("|",1)[0].replace("#","").strip())
    except Exception:
        await update.message.reply_text("Qozon raqami noto‘g‘ri.")
        return ADJ_FURNACE
    rows=context.user_data.get("adjust_rows",[])
    row=next((x for x in rows if int(x["id"])==furnace_id),None)
    if not row:
        await update.message.reply_text("Qozon topilmadi.")
        return ADJ_FURNACE
    materials=await db.furnace_materials_for_adjustment(pool_from(context),furnace_id)
    context.user_data["adjust_furnace_id"]=furnace_id
    context.user_data["adjust_materials"]=materials
    buttons=[[f"{x['material']} — {fmt_kg(x['kg'])} kg"] for x in materials]
    buttons.append([CANCEL])
    await update.message.reply_text(
        f"🔥 Qozon #{furnace_id}\n📦 Materialni tanlang:",
        reply_markup=ReplyKeyboardMarkup(buttons,resize_keyboard=True)
    )
    return ADJ_MATERIAL

async def adjust_material(update,context):
    text=update.message.text.strip()
    materials=context.user_data.get("adjust_materials",[])
    selected=None
    for x in materials:
        if text.startswith(x["material"]+" —"):
            selected=x
            break
    if not selected:
        await update.message.reply_text("Materialni tugmadan tanlang.")
        return ADJ_MATERIAL
    context.user_data["adjust_material"]=selected["material"]
    context.user_data["adjust_input_kg"]=selected["kg"]
    await update.message.reply_text(
        f"📦 {selected['material']}: {fmt_kg(selected['kg'])} kg\n"
        "Qaysi o‘zgarish?",
        reply_markup=ReplyKeyboardMarkup([["⬇️ Skidka","↩️ Vozvrat"],[CANCEL]],resize_keyboard=True)
    )
    return ADJ_TYPE

async def adjust_type(update,context):
    mp={"⬇️ Skidka":"skidka","↩️ Vozvrat":"vozvrat"}
    t=mp.get(update.message.text.strip())
    if not t:
        await update.message.reply_text("⬇️ Skidka yoki ↩️ Vozvrat ni tanlang.")
        return ADJ_TYPE
    context.user_data["adjust_type"]=t
    await update.message.reply_text(
        f"⚖️ {t.title()} kg miqdorini kiriting:",
        reply_markup=cancel_markup()
    )
    return ADJ_KG

async def adjust_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0:
        await update.message.reply_text("Kg noto‘g‘ri. Masalan: 5")
        return ADJ_KG
    d=context.user_data
    try:
        aid=await db.create_furnace_adjustment(
            pool_from(context),d["adjust_furnace_id"],d["adjust_material"],d["adjust_type"],v
        )
        rows=await db.get_furnace_adjustments(pool_from(context),d["adjust_furnace_id"])
        last=next(r for r in rows if int(r["id"])==aid)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}",reply_markup=menu_markup())
        context.user_data.clear()
        return ConversationHandler.END
    typ="Skidka" if d["adjust_type"]=="skidka" else "Vozvrat"
    await update.message.reply_text(
        f"✅ {typ} saqlandi\n"
        f"🔥 Qozon #{d['adjust_furnace_id']}\n"
        f"📦 {d['adjust_material']}\n"
        f"⚖️ {fmt_kg(v)} kg\n"
        f"📊 {float(last['percent']):.2f}%\n\n"
        "Yana boshqa materialga skidka/vozvrat kiritasizmi?",
        reply_markup=ReplyKeyboardMarkup([["✅ Ha","❌ Yo‘q"],[CANCEL]],resize_keyboard=True)
    )
    return ADJ_MORE

async def adjust_more(update,context):
    t=update.message.text.strip()
    if t=="❌ Yo‘q":
        context.user_data.clear()
        await update.message.reply_text("✅ Saqlandi.",reply_markup=menu_markup())
        return ConversationHandler.END
    if t=="✅ Ha":
        materials=context.user_data.get("adjust_materials",[])
        buttons=[[f"{x['material']} — {fmt_kg(x['kg'])} kg"] for x in materials]
        buttons.append([CANCEL])
        await update.message.reply_text("📦 Materialni tanlang:",reply_markup=ReplyKeyboardMarkup(buttons,resize_keyboard=True))
        return ADJ_MATERIAL
    await update.message.reply_text("✅ Ha yoki ❌ Yo‘q ni tanlang.")
    return ADJ_MORE

FINISHED_PRODUCTS=["Mis truba","Latun Truba","Latun Uzuk","Alyumin uzuk"]

def finished_markup():
    return ReplyKeyboardMarkup(
        [[x] for x in FINISHED_PRODUCTS],
        [["📊 Jami qoldiq"],["➕ Boshqa material"],[CANCEL]],
        resize_keyboard=True
    )

async def finished_start(update,context):
    await update.message.reply_text(
        "🏭 Tayyor mahsulot bo‘limi.\n"
        "Mahsulot turini tanlang:",
        reply_markup=finished_markup()
    )
    return S_PRODUCT

async def finished_product(update,context):
    name=update.message.text.strip()
    if name=="📊 Jami qoldiq":
        await finished_list(update,context)
        return S_PRODUCT
    if name=="➕ Boshqa material":
        context.user_data["finished_custom"]=True
        await update.message.reply_text("✍️ Mahsulot nomini yozing:", reply_markup=cancel_markup())
        return S_PRODUCT
    if context.user_data.pop("finished_custom",False):
        context.user_data["finished"]={"product":name}
    elif name not in FINISHED_PRODUCTS:
        await update.message.reply_text("Variantlardan birini tanlang:", reply_markup=finished_markup())
        return S_PRODUCT
    else:
        context.user_data["finished"]={"product":name}
    context.user_data["finished"]={"product":name}
    await update.message.reply_text("⚖️ Necha kg tayyor mahsulot chiqdi?", reply_markup=cancel_markup())
    return S_KG

async def finished_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return S_KG
    d=context.user_data["finished"]
    try:
        pid=await db.create_finished_product(pool_from(context),date.today(),d["product"],v)
    except Exception as e:
        await update.message.reply_text(f"❌ Saqlashda xato: {e}",reply_markup=menu_markup())
        return ConversationHandler.END
    summary=await db.finished_products_summary(pool_from(context))
    line=next((x for x in summary if x["product"].lower()==d["product"].lower()),None)
    await update.message.reply_text(
        f"✅ Tayyor mahsulot #{pid} saqlandi.\n\n"
        f"🏭 Mahsulot: {d['product']}\n"
        f"➕ Qo‘shildi: {fmt_kg(v)} kg\n"
        f"📦 Jami ishlab chiqarilgan: {fmt_kg(line['produced_kg'])} kg\n"
        f"💰 Sotilgan: {fmt_kg(line['sold_kg'])} kg\n"
        f"📦 Omborda: {fmt_kg(line['stock_kg'])} kg",
        reply_markup=menu_markup()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def finished_list(update,context):
    rows=await db.finished_products_summary(pool_from(context))
    lines=["🏭 TAYYOR MAHSULOTLAR",""]
    for x in rows:
        lines.append(
            f"• {x['product']}\n"
            f"  Ishlab chiqarilgan: {fmt_kg(x['produced_kg'])} kg\n"
            f"  Sotilgan: {fmt_kg(x['sold_kg'])} kg\n"
            f"  Qoldiq: {fmt_kg(x['stock_kg'])} kg"
        )
    await update.message.reply_text(
        "\n\n".join(lines) if len(lines)>2 else "🏭 Hozircha tayyor mahsulot yo‘q.",
        reply_markup=menu_markup()
    )

async def sale_start(update,context):
    context.user_data["sale"]={}; await update.message.reply_text("📦 Sotilgan tayyor mahsulot nomini kiriting:",reply_markup=cancel_markup()); return S_PRODUCT
async def sale_product(update,context):
    context.user_data["sale"]["product"]=update.message.text.strip(); await update.message.reply_text("⚖️ Necha kg sotildi?"); return S_KG
async def sale_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0: await update.message.reply_text("Kg noto‘g‘ri."); return S_KG
    context.user_data["sale"]["kg"]=v; await update.message.reply_text("💵 Sotuv narxi (1 kg):"); return S_PRICE
async def sale_price(update,context):
    v=parse_decimal(update.message.text)
    if v is None: await update.message.reply_text("Narx noto‘g‘ri."); return S_PRICE
    context.user_data["sale"]["sale_price"]=v; await update.message.reply_text("📋 Tannarx (1 kg):"); return S_COST
async def sale_cost(update,context):
    v=parse_decimal(update.message.text)
    if v is None: await update.message.reply_text("Tannarx noto‘g‘ri."); return S_COST
    d=context.user_data["sale"]; pool=pool_from(context)
    try: sid=await db.create_sale(pool,date.today(),d["product"],d["kg"],d["sale_price"],v)
    except Exception as e: await update.message.reply_text(f"❌ Saqlashda xato: {e}"); return ConversationHandler.END
    profit=d["kg"]*(d["sale_price"]-v)
    await update.message.reply_text(f"✅ Sotuv #{sid} saqlandi.\n📦 {d['product']}\n⚖️ {fmt_kg(d['kg'])} kg\n💰 Tushum: {d['kg']*d['sale_price']:,.0f} so‘m\n{'🟢 Foyda' if profit>=0 else '🔴 Zarar'}: {abs(profit):,.0f} so‘m",reply_markup=menu_markup())
    context.user_data.clear(); return ConversationHandler.END

async def stock(update,context):
    rows=await db.stock_summary(pool_from(context))
    lines=["📦 OMBOR QOLDIG‘I",""]
    for r in rows:
        if abs(float(r["kg"]))>0.0001: lines.append(f"• {r['material']}: {fmt_kg(r['kg'])} kg")
    await update.message.reply_text("\n".join(lines) if len(lines)>2 else "📦 Ombor bo‘sh.",reply_markup=menu_markup())
async def report(update,context):
    r=await db.report(pool_from(context))
    await update.message.reply_text(f"📊 UMUMIY HISOBOT\n\n📦 Qabul qilingan: {fmt_kg(r['incoming_kg'])} kg\n🔥 Qozonlarga berilgan: {fmt_kg(r['issued_kg'])} kg\n📦 Xomashyo qoldig‘i: {fmt_kg(r['raw_stock_kg'])} kg\n🏭 Tayyor ishlab chiqarilgan: {fmt_kg(r['finished_kg'])} kg\n💰 Sotilgan: {fmt_kg(r['sold_kg'])} kg\n💵 Tushum: {r['revenue']:,.0f} so‘m\n🟢 Foyda: {r['profit']:,.0f} so‘m\n🔴 Zarar: {r['loss']:,.0f} so‘m",reply_markup=menu_markup())
async def profit(update,context): await update.message.reply_text(f"🟢 Jami foyda: {max(await db.profit_loss(pool_from(context)),0):,.0f} so‘m")
async def loss(update,context): await update.message.reply_text(f"🔴 Jami zarar: {max(-(await db.profit_loss(pool_from(context))),0):,.0f} so‘m")

async def search_start(update,context):
    await update.message.reply_text("🔎 Mashina raqami yoki shaxs ismini kiriting:",reply_markup=cancel_markup()); return SEARCH_TEXT
async def search_text(update,context):
    rows=await db.search_loads(pool_from(context),update.message.text.strip())
    if not rows: await update.message.reply_text("Topilmadi.",reply_markup=menu_markup()); return ConversationHandler.END
    lines=["🔎 TOPILGAN YUKLAR",""]
    for r in rows:
        initial=sum(Decimal(str(x["initial_kg"])) for x in r["items"])
        accepted=initial-Decimal(str(r["skidka_kg"]))-Decimal(str(r["vozvrat_kg"]))
        lines.append(f"#{r['id']} | {r['vehicle_no']} | {r['person_name']}\n📅 {r['received_date']} | 📦 {fmt_kg(accepted)} kg")
    await update.message.reply_text("\n\n".join(lines),reply_markup=menu_markup()); return ConversationHandler.END

async def edit_start(update,context):
    await update.message.reply_text("✏️ Nimani o‘zgartirasiz?",reply_markup=ReplyKeyboardMarkup([["📥 Yuk kg","💰 Sotuv kg"],["🏭 Tayyor mahsulot kg"],["🔥 Qozon material kg","🔥 Qozon natijasi"],[CANCEL]],resize_keyboard=True)); return EDIT_TYPE
async def edit_type(update,context):
    t=update.message.text
    mp={"📥 Yuk kg":"load","💰 Sotuv kg":"sale","🏭 Tayyor mahsulot kg":"finished","🔥 Qozon material kg":"fitem","🔥 Qozon natijasi":"fresult"}
    if t not in mp: await update.message.reply_text("Tugmalardan birini tanlang."); return EDIT_TYPE
    context.user_data["edit_type"]=mp[t]; await update.message.reply_text("ID raqamini kiriting:"); return EDIT_ID
async def edit_id(update,context):
    try: i=int(update.message.text.strip())
    except: await update.message.reply_text("ID raqamini kiriting, masalan 12"); return EDIT_ID
    context.user_data["edit_id"]=i; typ=context.user_data["edit_type"]
    if typ=="sale": await update.message.reply_text("Sotuvning yangi kg miqdorini kiriting:"); return EDIT_KG
    if typ=="finished": await update.message.reply_text("Tayyor mahsulot yozuvining yangi kg miqdorini kiriting:"); return EDIT_KG
    if typ=="load": await update.message.reply_text("Material nomini kiriting (masalan Sariq):"); return EDIT_MATERIAL
    if typ=="fitem": await update.message.reply_text("Material nomini kiriting:"); return EDIT_MATERIAL
    await update.message.reply_text("Yangi tayyor kg miqdorini kiriting:"); return EDIT_FINISHED
async def edit_material(update,context):
    context.user_data["edit_material"]=update.message.text.strip(); await update.message.reply_text("Yangi kg miqdorini kiriting:"); return EDIT_KG
async def edit_kg(update,context):
    v=parse_decimal(update.message.text)
    if v is None or v<=0: await update.message.reply_text("Kg noto‘g‘ri."); return EDIT_KG
    pool=pool_from(context); typ=context.user_data["edit_type"]; i=context.user_data["edit_id"]
    try:
        if typ=="sale": ok=await db.update_sale_kg(pool,i,v)
        elif typ=="finished": ok=await db.update_finished_product_kg(pool,i,v)
        else: ok=await db.update_load_item_kg(pool,i,context.user_data["edit_material"],v) if typ=="load" else await db.update_furnace_item_kg(pool,i,context.user_data["edit_material"],v)
    except Exception as e: await update.message.reply_text(f"❌ {e}",reply_markup=menu_markup()); return ConversationHandler.END
    await update.message.reply_text("✅ Kg muvaffaqiyatli o‘zgartirildi." if ok else "❌ ID yoki material topilmadi.",reply_markup=menu_markup()); context.user_data.clear(); return ConversationHandler.END
async def edit_finished(update,context):
    v=parse_decimal(update.message.text)
    if v is None: await update.message.reply_text("Kg noto‘g‘ri."); return EDIT_FINISHED
    context.user_data["edit_finished"]=v; await update.message.reply_text("Yangi chiqit kg miqdorini kiriting:"); return EDIT_SCRAP
async def edit_scrap(update,context):
    v=parse_decimal(update.message.text)
    if v is None: await update.message.reply_text("Kg noto‘g‘ri."); return EDIT_SCRAP
    try: ok=await db.update_furnace_result(pool_from(context),context.user_data["edit_id"],context.user_data["edit_finished"],v)
    except Exception as e: await update.message.reply_text(f"❌ {e}",reply_markup=menu_markup()); return ConversationHandler.END
    await update.message.reply_text("✅ Qozon natijasi o‘zgartirildi." if ok else "❌ Qozon ID topilmadi.",reply_markup=menu_markup()); context.user_data.clear(); return ConversationHandler.END

async def error_handler(update,context): logger.exception("Unhandled bot error",exc_info=context.error)

async def fallback_text(update,context):
    await update.message.reply_text("Menyudan kerakli bo‘limni tanlang.",reply_markup=menu_markup())

def register_handlers(application):
    load=ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{ADD_LOAD}$"),load_start)],
      states={LOAD_CONFIRM:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_confirm)],LOAD_DATE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_date)],
      LOAD_VEHICLE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_vehicle)],LOAD_PERSON:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_person)],
      LOAD_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_material)],LOAD_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_kg)],
      LOAD_PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_price)],LOAD_MORE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_more)],LOAD_CUSTOM:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_custom)]},
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
    application.add_handler(CommandHandler("start",start)); application.add_handler(CommandHandler("help",help_command)); application.add_handler(CommandHandler("cancel",cancel))
    application.add_handler(load)
    for kind,title in [("mis",COPPER),("latun",BRASS),("alyumin",ALUMINUM)]:
        conv=ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{title}$"),furnace_start_factory(kind,title))],
          states={F_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_material)],F_CUSTOM:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_custom)],F_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_kg)],
          F_MORE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_more)],F_SCRAP:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_scrap)],
          F_CUSTOM:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_custom)],
          F_ADJ_CONFIRM:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_adjust_confirm)],
          F_ADJ_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_adjust_material)],
          F_ADJ_TYPE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_adjust_type)],
          F_ADJ_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_adjust_kg)],
          F_ADJ_MORE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),furnace_adjust_more)]},
          fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
        application.add_handler(conv)
    finished=ConversationHandler(
      entry_points=[MessageHandler(filters.Regex(f"^{FINISHED}$"),finished_start)],
      states={
        S_PRODUCT:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),finished_product)],
        S_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),finished_kg)]
      },
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]
    )
    application.add_handler(finished)

    sale=ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{SALE}$"),sale_start)],
      states={S_PRODUCT:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),sale_product)],S_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),sale_kg)],
      S_PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),sale_price)],S_COST:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),sale_cost)]},
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
    search=ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{SEARCH}$"),search_start)],
      states={SEARCH_TEXT:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),search_text)]},
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
    edit=ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{EDIT}$"),edit_start)],
      states={EDIT_TYPE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_type)],EDIT_ID:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_id)],
      EDIT_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_material)],EDIT_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_kg)],
      EDIT_FINISHED:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_finished)],EDIT_SCRAP:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),edit_scrap)]},
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
    adjust=ConversationHandler(
      entry_points=[MessageHandler(filters.Regex(f"^{ADJUST}$"),adjust_start)],
      states={
        ADJ_FURNACE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),adjust_furnace)],
        ADJ_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),adjust_material)],
        ADJ_TYPE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),adjust_type)],
        ADJ_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),adjust_kg)],
        ADJ_MORE:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),adjust_more)]
      },
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]
    )
    application.add_handler(adjust)
    load_adjust=ConversationHandler(
      entry_points=[MessageHandler(filters.Regex(f"^{ADJUST}$"),load_adjust_start)],
      states={
        LOADADJ_SEARCH:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_adjust_search)],
        LOADADJ_LOAD:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_adjust_load)],
        LOADADJ_MATERIAL:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_adjust_material)],
        LOADADJ_SKIDKA_PCT:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_adjust_skidka_pct)],
        LOADADJ_VOZVRAT_KG:[MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),load_adjust_vozvrat_kg)]
      },
      fallbacks=[CommandHandler("cancel",cancel),MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]
    )
    application.add_handler(load_adjust)
    for h in [sale,search,edit]: application.add_handler(h)
    application.add_handler(MessageHandler(filters.Regex(f"^{STOCK}$"),stock)); application.add_handler(MessageHandler(filters.Regex(f"^{REPORT}$"),report))
    application.add_handler(MessageHandler(filters.Regex(f"^{PROFIT}$"),profit)); application.add_handler(MessageHandler(filters.Regex(f"^{LOSS}$"),loss))
    application.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND&~filters.Regex(f"^{CANCEL}$"),fallback_text))
