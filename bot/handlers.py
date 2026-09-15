"""Factory accounting Telegram handlers."""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import db

logger = logging.getLogger(__name__)

DB_KEY = "db"
REDIS_KEY = "redis"

ADD_LOAD = "➕ Yuk qabul qilish"
COPPER = "🔥 Mis qozon"
BRASS = "🔥 Latun qozon"
ALUMINUM = "🔥 Alyumin qozon"
SALE = "💰 Sotuv"
STOCK = "📦 Ombor"
REPORT = "📊 Hisobot"
SEARCH = "🔎 Qidirish"
PROFIT = "🟢 Foyda"
LOSS = "🔴 Zarar"
CANCEL = "❌ Bekor qilish"

MATERIALS = [
    "Qizil oddiy", "Tros", "Qizil lahim", "Sariq", "Radiator Sariq",
    "Radiator qizil", "Quyma sink", "Karbyurator", "Teplo",
    "Alyumin zapchast", "Alyumin chushka",
]

FURNACE_MATERIALS = {
    "mis": ["Qizil oddiy", "Tros", "Qizil lahim"],
    "latun": ["Sariq", "Radiator Sariq", "Radiator qizil",
              "Quyma sink", "Karbyurator", "Teplo", "Qizil skidka"],
    "alyumin": ["Alyumin zapchast", "Alyumin chushka"],
}

MAIN_KEYBOARD = [
    [ADD_LOAD],
    [COPPER, BRASS],
    [ALUMINUM, SALE],
    [STOCK, REPORT],
    [SEARCH, PROFIT, LOSS],
]

LOAD_DATE, LOAD_VEHICLE, LOAD_PERSON, LOAD_MATERIAL, LOAD_KG, LOAD_PRICE, LOAD_MORE, LOAD_SKIDKA, LOAD_VOZVRAT = range(9)
FURNACE_DATE, FURNACE_MATERIAL, FURNACE_KG, FURNACE_MORE, FURNACE_FINISHED, FURNACE_SCRAP = range(9, 15)
SALE_PRODUCT, SALE_KG, SALE_PRICE, SALE_COST = range(15, 19)
SEARCH_TEXT = 19


def menu_markup():
    return ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)


def cancel_markup():
    return ReplyKeyboardMarkup([[CANCEL]], resize_keyboard=True)


def parse_decimal(text: str):
    try:
        value = Decimal(text.replace(" ", "").replace(",", "."))
        if value < 0:
            return None
        return value
    except (InvalidOperation, ValueError):
        return None


def pool_from(context):
    return context.application.bot_data.get(DB_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = pool_from(context)
    if pool:
        user = update.effective_user
        try:
            await db.upsert_user(pool, user.id, user.username, user.first_name)
        except Exception:
            logger.exception("Could not save user")
    await update.message.reply_text(
        "🏭 Zavod Hisob botiga xush kelibsiz!\n\n"
        "Bu bot orqali yuk, qozon, ombor, sotuv, foyda va zarar hisoblanadi.",
        reply_markup=menu_markup(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Asosiy menyudan kerakli bo‘limni tanlang.\n"
        "Ma'lumot kiritishda ❌ Bekor qilish tugmasidan foydalanishingiz mumkin.",
        reply_markup=menu_markup(),
    )


async def set_bot_commands(application: Application):
    await application.bot.set_my_commands([
        ("start", "Asosiy menyu"),
        ("help", "Yordam"),
        ("cancel", "Joriy amalni bekor qilish"),
    ])


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=menu_markup())
    return ConversationHandler.END


# ---------- Incoming loads ----------

async def load_start(update, context):
    context.user_data["load"] = {"items": []}
    await update.message.reply_text(
        "📅 Yuk kelgan sanani kiriting.\nMasalan: 15.09.2026",
        reply_markup=cancel_markup(),
    )
    return LOAD_DATE


async def load_date(update, context):
    text = update.message.text.strip()
    try:
        d, m, y = map(int, text.split("."))
        context.user_data["load"]["date"] = date(y, m, d)
    except Exception:
        await update.message.reply_text("Sana noto‘g‘ri. Masalan: 15.09.2026")
        return LOAD_DATE
    await update.message.reply_text("🚚 Mashina raqamini kiriting:")
    return LOAD_VEHICLE


async def load_vehicle(update, context):
    context.user_data["load"]["vehicle"] = update.message.text.strip()
    await update.message.reply_text("👤 Haydovchi / shaxs ismini kiriting:")
    return LOAD_PERSON


async def load_person(update, context):
    context.user_data["load"]["person"] = update.message.text.strip()
    await update.message.reply_text(
        "📦 Material nomini yozing.\n"
        "Masalan: Sariq, Qizil oddiy, Tros..."
    )
    return LOAD_MATERIAL


async def load_material(update, context):
    context.user_data["load"]["current_material"] = update.message.text.strip()
    await update.message.reply_text("⚖️ Shu materialning boshlang‘ich kg miqdorini kiriting:")
    return LOAD_KG


async def load_kg(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value <= 0:
        await update.message.reply_text("Kg noto‘g‘ri. Masalan: 3000")
        return LOAD_KG
    context.user_data["load"]["current_kg"] = value
    await update.message.reply_text("💵 1 kg narxini kiriting:")
    return LOAD_PRICE


async def load_price(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value < 0:
        await update.message.reply_text("Narx noto‘g‘ri. Masalan: 48000")
        return LOAD_PRICE

    data = context.user_data["load"]
    data["items"].append({
        "material": data.pop("current_material"),
        "initial_kg": data.pop("current_kg"),
        "price": value,
    })

    await update.message.reply_text(
        "Yana boshqa material qo‘shasizmi?",
        reply_markup=ReplyKeyboardMarkup([["➕ Ha", "✅ Yo‘q"], [CANCEL]], resize_keyboard=True),
    )
    return LOAD_MORE


async def load_more(update, context):
    text = update.message.text
    if text == "➕ Ha":
        await update.message.reply_text("📦 Keyingi material nomini kiriting:")
        return LOAD_MATERIAL

    if text != "✅ Yo‘q":
        await update.message.reply_text("➕ Ha yoki ✅ Yo‘q ni tanlang.")
        return LOAD_MORE

    await update.message.reply_text("⬇️ Skidka kg kiriting. Bo‘lmasa 0:")
    return LOAD_SKIDKA


async def load_skidka(update, context):
    value = parse_decimal(update.message.text)
    if value is None:
        await update.message.reply_text("Raqam kiriting. Masalan: 100 yoki 0")
        return LOAD_SKIDKA
    context.user_data["load"]["skidka"] = value
    await update.message.reply_text("↩️ Vozvrat kg kiriting. Bo‘lmasa 0:")
    return LOAD_VOZVRAT


async def load_vozvrat(update, context):
    value = parse_decimal(update.message.text)
    if value is None:
        await update.message.reply_text("Raqam kiriting. Masalan: 100 yoki 0")
        return LOAD_VOZVRAT

    data = context.user_data["load"]
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan. Railway Variables ni tekshirish kerak.")
        return ConversationHandler.END

    data["vozvrat"] = value
    try:
        load_id = await db.create_load(
            pool,
            data["date"],
            data["vehicle"],
            data["person"],
            data["items"],
            data["skidka"],
            data["vozvrat"],
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Saqlashda xato: {exc}")
        return ConversationHandler.END

    initial_total = sum(i["initial_kg"] * i["price"] for i in data["items"])
    accepted_kg = sum(i["initial_kg"] for i in data["items"]) - data["skidka"] - data["vozvrat"]

    await update.message.reply_text(
        f"✅ Yuk #{load_id} saqlandi.\n\n"
        f"🚚 Mashina: {data['vehicle']}\n"
        f"👤 Shaxs: {data['person']}\n"
        f"⚖️ Boshlang‘ich: {sum(i['initial_kg'] for i in data['items']):,.3f} kg\n"
        f"⬇️ Skidka: {data['skidka']:,.3f} kg\n"
        f"↩️ Vozvrat: {data['vozvrat']:,.3f} kg\n"
        f"📦 Qabul qilingan: {accepted_kg:,.3f} kg\n"
        f"💵 Boshlang‘ich qiymat: {initial_total:,.0f} so‘m",
        reply_markup=menu_markup(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ---------- Furnaces ----------

def furnace_start_factory(kind, title):
    async def start_furnace(update, context):
        context.user_data["furnace"] = {"kind": kind, "items": []}
        await update.message.reply_text(
            f"{title}\n📅 Sana kiriting. Masalan: 15.09.2026",
            reply_markup=cancel_markup(),
        )
        return FURNACE_DATE
    return start_furnace


async def furnace_date(update, context):
    try:
        d, m, y = map(int, update.message.text.strip().split("."))
        context.user_data["furnace"]["date"] = date(y, m, d)
    except Exception:
        await update.message.reply_text("Sana noto‘g‘ri. Masalan: 15.09.2026")
        return FURNACE_DATE

    kind = context.user_data["furnace"]["kind"]
    names = ", ".join(FURNACE_MATERIALS[kind])
    await update.message.reply_text(
        f"Material nomini yozing.\nRuxsat etilganlar: {names}"
    )
    return FURNACE_MATERIAL


async def furnace_material(update, context):
    context.user_data["furnace"]["current_material"] = update.message.text.strip()
    await update.message.reply_text("⚖️ Shu materialdan necha kg qozonga berildi?")
    return FURNACE_KG


async def furnace_kg(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value <= 0:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return FURNACE_KG

    data = context.user_data["furnace"]
    data["items"].append({
        "material": data.pop("current_material"),
        "kg": value,
    })
    await update.message.reply_text(
        "Yana material qo‘shasizmi?",
        reply_markup=ReplyKeyboardMarkup([["➕ Ha", "✅ Yo‘q"], [CANCEL]], resize_keyboard=True),
    )
    return FURNACE_MORE


async def furnace_more(update, context):
    if update.message.text == "➕ Ha":
        await update.message.reply_text("Keyingi material nomini kiriting:")
        return FURNACE_MATERIAL
    if update.message.text != "✅ Yo‘q":
        await update.message.reply_text("➕ Ha yoki ✅ Yo‘q ni tanlang.")
        return FURNACE_MORE
    await update.message.reply_text("🏭 Tayyor mahsulot necha kg chiqdi?")
    return FURNACE_FINISHED


async def furnace_finished(update, context):
    value = parse_decimal(update.message.text)
    if value is None:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return FURNACE_FINISHED
    context.user_data["furnace"]["finished"] = value
    await update.message.reply_text("♻️ Chiqit necha kg chiqdi?")
    return FURNACE_SCRAP


async def furnace_scrap(update, context):
    value = parse_decimal(update.message.text)
    if value is None:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return FURNACE_SCRAP

    data = context.user_data["furnace"]
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return ConversationHandler.END

    input_kg = sum(x["kg"] for x in data["items"])
    loss = input_kg - data["finished"] - value

    if loss < 0:
        await update.message.reply_text(
            f"❌ Hisob noto‘g‘ri: kirim {input_kg:,.3f} kg, "
            f"tayyor + chiqit {data['finished'] + value:,.3f} kg."
        )
        return FURNACE_SCRAP

    try:
        furnace_id = await db.create_furnace(
            pool, data["date"], data["kind"], data["items"],
            data["finished"], value
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Saqlashda xato: {exc}")
        return ConversationHandler.END

    finished_pct = (data["finished"] / input_kg * 100) if input_kg else 0
    scrap_pct = (value / input_kg * 100) if input_kg else 0
    loss_pct = (loss / input_kg * 100) if input_kg else 0

    await update.message.reply_text(
        f"✅ Qozon #{furnace_id} saqlandi.\n\n"
        f"⚖️ Kirim: {input_kg:,.3f} kg\n"
        f"🏭 Tayyor: {data['finished']:,.3f} kg ({finished_pct:.2f}%)\n"
        f"♻️ Chiqit: {value:,.3f} kg ({scrap_pct:.2f}%)\n"
        f"🔻 Jarayon yo‘qotishi: {loss:,.3f} kg ({loss_pct:.2f}%)\n\n"
        f"Balans: {data['finished'] + value + loss:,.3f} kg",
        reply_markup=menu_markup(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ---------- Sales ----------

async def sale_start(update, context):
    context.user_data["sale"] = {}
    await update.message.reply_text("📦 Sotilgan mahsulot nomini kiriting:", reply_markup=cancel_markup())
    return SALE_PRODUCT


async def sale_product(update, context):
    context.user_data["sale"]["product"] = update.message.text.strip()
    await update.message.reply_text("⚖️ Necha kg sotildi?")
    return SALE_KG


async def sale_kg(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value <= 0:
        await update.message.reply_text("Kg noto‘g‘ri.")
        return SALE_KG
    context.user_data["sale"]["kg"] = value
    await update.message.reply_text("💵 Sotuv narxi (1 kg) qancha?")
    return SALE_PRICE


async def sale_price(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value < 0:
        await update.message.reply_text("Narx noto‘g‘ri.")
        return SALE_PRICE
    context.user_data["sale"]["sale_price"] = value
    await update.message.reply_text("📋 Tannarx (1 kg) qancha?")
    return SALE_COST


async def sale_cost(update, context):
    value = parse_decimal(update.message.text)
    if value is None or value < 0:
        await update.message.reply_text("Tannarx noto‘g‘ri.")
        return SALE_COST

    data = context.user_data["sale"]
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return ConversationHandler.END

    try:
        sale_id = await db.create_sale(
            pool, date.today(), data["product"], data["kg"],
            data["sale_price"], value
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Saqlashda xato: {exc}")
        return ConversationHandler.END

    revenue = data["kg"] * data["sale_price"]
    profit = data["kg"] * (data["sale_price"] - value)

    await update.message.reply_text(
        f"✅ Sotuv #{sale_id} saqlandi.\n\n"
        f"📦 Mahsulot: {data['product']}\n"
        f"⚖️ Miqdor: {data['kg']:,.3f} kg\n"
        f"💰 Tushum: {revenue:,.0f} so‘m\n"
        f"{'🟢 Foyda' if profit >= 0 else '🔴 Zarar'}: {abs(profit):,.0f} so‘m",
        reply_markup=menu_markup(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ---------- Reports / stock / search ----------

async def stock(update, context):
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return
    rows = await db.stock_summary(pool)
    if not rows:
        await update.message.reply_text("📦 Ombor hozircha bo‘sh.")
        return
    lines = ["📦 OMBOR QOLDIG‘I", ""]
    for row in rows:
        kg = row["kg"]
        if abs(float(kg)) > 0.0001:
            lines.append(f"• {row['material']}: {kg:,.3f} kg")
    await update.message.reply_text("\n".join(lines) if len(lines) > 2 else "📦 Ombor hozircha bo‘sh.")


async def report(update, context):
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return
    r = await db.report(pool)
    await update.message.reply_text(
        "📊 UMUMIY HISOBOT\n\n"
        f"📦 Jami kirgan: {r['incoming_kg']:,.3f} kg\n"
        f"🔥 Qozonlarga berilgan: {r['issued_kg']:,.3f} kg\n"
        f"📦 Xomashyo qoldig‘i: {r['raw_stock_kg']:,.3f} kg\n"
        f"🏭 Ishlab chiqarilgan: {r['finished_kg']:,.3f} kg\n"
        f"💵 Tushum: {r['revenue']:,.0f} so‘m\n"
        f"🟢 Foyda: {r['profit']:,.0f} so‘m\n"
        f"🔴 Zarar: {r['loss']:,.0f} so‘m"
    )


async def search_start(update, context):
    await update.message.reply_text("🔎 Mashina raqami yoki shaxs ismini kiriting:", reply_markup=cancel_markup())
    return SEARCH_TEXT


async def search_text(update, context):
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.", reply_markup=menu_markup())
        return ConversationHandler.END

    rows = await db.search_loads(pool, update.message.text.strip())
    if not rows:
        await update.message.reply_text("Topilmadi.", reply_markup=menu_markup())
        return ConversationHandler.END

    lines = ["🔎 TOPILGAN YUKLAR", ""]
    for r in rows:
        initial = sum(Decimal(str(x["initial_kg"])) for x in r["items"])
        accepted = initial - Decimal(str(r["skidka_kg"])) - Decimal(str(r["vozvrat_kg"]))
        lines.append(
            f"#{r['id']} | {r['vehicle_no']} | {r['person_name']}\n"
            f"📅 {r['received_date']} | {accepted:,.3f} kg qabul qilingan"
        )
    await update.message.reply_text("\n\n".join(lines), reply_markup=menu_markup())
    return ConversationHandler.END


async def profit(update, context):
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return
    value = await db.profit_loss(pool)
    await update.message.reply_text(f"🟢 Jami foyda: {max(value, 0):,.0f} so‘m")


async def loss(update, context):
    pool = pool_from(context)
    if pool is None:
        await update.message.reply_text("⚠️ Baza ulanmagan.")
        return
    value = await db.profit_loss(pool)
    await update.message.reply_text(f"🔴 Jami zarar: {max(-value, 0):,.0f} so‘m")


async def text_router(update, context):
    text = update.message.text
    mapping = {
        ADD_LOAD: load_start,
        STOCK: stock,
        REPORT: report,
        SEARCH: search_start,
        PROFIT: profit,
        LOSS: loss,
    }
    if text in mapping:
        result = await mapping[text](update, context)
        return result

    await update.message.reply_text(
        "Menyudan kerakli bo‘limni tanlang.",
        reply_markup=menu_markup(),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled bot error", exc_info=context.error)


def register_handlers(application: Application):
    load_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{ADD_LOAD}$"), load_start)],
        states={
            LOAD_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_date)],
            LOAD_VEHICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_vehicle)],
            LOAD_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_person)],
            LOAD_MATERIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_material)],
            LOAD_KG: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_kg)],
            LOAD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_price)],
            LOAD_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_more)],
            LOAD_SKIDKA: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_skidka)],
            LOAD_VOZVRAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, load_vozvrat)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
    )

    furnace_convs = []
    for kind, title in [
        ("mis", COPPER),
        ("latun", BRASS),
        ("alyumin", ALUMINUM),
    ]:
        start_fn = furnace_start_factory(kind, title)
        furnace_convs.append(
            ConversationHandler(
                entry_points=[MessageHandler(filters.Regex(f"^{title}$"), start_fn)],
                states={
                    FURNACE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_date)],
                    FURNACE_MATERIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_material)],
                    FURNACE_KG: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_kg)],
                    FURNACE_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_more)],
                    FURNACE_FINISHED: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_finished)],
                    FURNACE_SCRAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_scrap)],
                },
                fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
            )
        )

    sale_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{SALE}$"), sale_start)],
        states={
            SALE_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_product)],
            SALE_KG: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_kg)],
            SALE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_price)],
            SALE_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_cost)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
    )

    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{SEARCH}$"), search_start)],
        states={SEARCH_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_text)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))

    application.add_handler(load_conv)
    for conv in furnace_convs:
        application.add_handler(conv)
    application.add_handler(sale_conv)
    application.add_handler(search_conv)

    application.add_handler(MessageHandler(filters.Regex(f"^{STOCK}$"), stock))
    application.add_handler(MessageHandler(filters.Regex(f"^{REPORT}$"), report))
    application.add_handler(MessageHandler(filters.Regex(f"^{PROFIT}$"), profit))
    application.add_handler(MessageHandler(filters.Regex(f"^{LOSS}$"), loss))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
