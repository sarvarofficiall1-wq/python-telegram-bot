from __future__ import annotations

import logging
from decimal import Decimal

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import db

logger = logging.getLogger(__name__)

DB_KEY = "db"
REDIS_KEY = "redis"

CANCEL = "🚫 Bekor qilish"
YES = "✅ Ha"
NO = "❌ Yo‘q"

MENU = [
    ["📥 Yuk qabul qilish", "🔥 Qozonga berilgan mahsulotlar"],
    ["🏭 Tayyor mahsulot", "♻️ Chiqit ombori"],
    ["📦 Xomashyo ombori", "💰 Sotuv"],
    ["📊 Umumiy hisob", "⚙️ Xarajatlar"],
]

LOAD_PRODUCTS = [
    ["Qizil oddiy", "Qizil Lahim"],
    ["Tros", "Sariq"],
    ["Karbyurator", "Qizil radiator"],
    ["Sariq radiator", "Sink quyma"],
    ["Teplo", "Alyumin zapchast"],
    ["Alyumin chushka", "➕ Boshqa mahsulot"],
    [CANCEL],
]

def menu_keyboard():
    return ReplyKeyboardMarkup(MENU, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[CANCEL]], resize_keyboard=True)

def product_keyboard():
    return ReplyKeyboardMarkup(LOAD_PRODUCTS, resize_keyboard=True)

def confirm_keyboard():
    return ReplyKeyboardMarkup([[YES, NO], [CANCEL]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏭 Zavod hisob botiga xush kelibsiz.",
        reply_markup=menu_keyboard(),
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚫 Bekor qilindi.", reply_markup=menu_keyboard())
    return ConversationHandler.END

# ---------------- YUK QABUL QILISH ----------------

async def load_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["load"] = {"products": []}
    await update.message.reply_text(
        "🚚 Mashina raqamini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 1

async def load_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["load"]["vehicle"] = update.message.text.strip()
    await update.message.reply_text(
        "👤 Ismi familiyasini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 2

async def load_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["load"]["name"] = update.message.text.strip()
    await update.message.reply_text("📦 Mahsulotni tanlang:", reply_markup=product_keyboard())
    return 3

async def load_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product = update.message.text.strip()
    if product == "➕ Boshqa mahsulot":
        await update.message.reply_text(
            "📦 Mahsulot nomini yozing:",
            reply_markup=cancel_keyboard(),
        )
        return 4

    context.user_data["load"]["current_product"] = product
    await update.message.reply_text(
        f"⚖️ {product}\n\nKg miqdorini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 5

async def load_custom_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product = update.message.text.strip()
    if not product:
        await update.message.reply_text("❗ Mahsulot nomini kiriting.")
        return 4

    context.user_data["load"]["current_product"] = product
    await update.message.reply_text(
        f"⚖️ {product}\n\nKg miqdorini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 5

async def load_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = Decimal(update.message.text.replace(",", "."))
        if weight <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("❗ Kg ni to‘g‘ri kiriting. Masalan: 1000 yoki 1031.5")
        return 5

    context.user_data["load"]["current_weight"] = weight
    await update.message.reply_text(
        "💰 1 kg narxini so‘mda kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 6

async def load_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = Decimal(update.message.text.replace(" ", "").replace(",", "."))
        if price < 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("❗ Narxni to‘g‘ri kiriting.")
        return 6

    context.user_data["load"]["current_price"] = price
    await update.message.reply_text(
        "📉 Skidka foizini kiriting. Skidka bo‘lmasa: 0",
        reply_markup=cancel_keyboard(),
    )
    return 7

async def load_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        discount = Decimal(update.message.text.replace(",", "."))
        if discount < 0 or discount > 100:
            raise ValueError
    except Exception:
        await update.message.reply_text("❗ Skidka 0 dan 100 gacha bo‘lishi kerak.")
        return 7

    context.user_data["load"]["current_discount"] = discount
    await update.message.reply_text(
        "↩️ Vozvrat kg ni kiriting. Vozvrat bo‘lmasa: 0",
        reply_markup=cancel_keyboard(),
    )
    return 8

async def load_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    x = context.user_data["load"]
    try:
        returned = Decimal(update.message.text.replace(",", "."))
        weight = x["current_weight"]
        if returned < 0 or returned > weight:
            raise ValueError
    except Exception:
        await update.message.reply_text("❗ Vozvrat kg miqdorini to‘g‘ri kiriting.")
        return 8

    product = x["current_product"]
    weight = x["current_weight"]
    price = x["current_price"]
    discount = x["current_discount"]

    payable = (weight - returned) * price * (Decimal("100") - discount) / Decimal("100")

    x["products"].append({
        "material": product,
        "kg": weight,
        "price": price,
        "skidka_pct": discount,
        "vozvrat_kg": returned,
        "payable": payable,
    })

    total_weight = sum(p["kg"] for p in x["products"])
    total_payable = sum(p["payable"] for p in x["products"])

    await update.message.reply_text(
        f"✅ {product} qo‘shildi.\n"
        f"⚖️ {weight} kg\n"
        f"💰 {price:,.0f} so‘m/kg\n"
        f"📉 Skidka: {discount}%\n"
        f"↩️ Vozvrat: {returned} kg\n"
        f"💵 To‘lov: {payable:,.0f} so‘m\n\n"
        f"📦 Jami: {total_weight} kg\n"
        f"💵 Jami to‘lov: {total_payable:,.0f} so‘m",
        reply_markup=ReplyKeyboardMarkup(
            [["➕ Yana mahsulot"], [YES, NO], [CANCEL]],
            resize_keyboard=True,
        ),
    )
    return 9

async def load_after_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "➕ Yana mahsulot":
        await update.message.reply_text("📦 Keyingi mahsulotni tanlang:", reply_markup=product_keyboard())
        return 3

    if text == NO:
        await update.message.reply_text(
            "❌ Tuzatish keyingi to‘liq versiyada alohida maydon tugmalari bilan ishlaydi.\n"
            "Hozir yukni qaytadan kiritishingiz mumkin.",
            reply_markup=cancel_keyboard(),
        )
        return 10

    if text == YES:
        x = context.user_data["load"]
        total_weight = sum(p["kg"] for p in x["products"])
        total_return = sum(p["vozvrat_kg"] for p in x["products"])
        total_payable = sum(p["payable"] for p in x["products"])

        details = ""
        for i, p in enumerate(x["products"], 1):
            details += (
                f"{i}. 📦 {p['material']}\n"
                f"   ⚖️ {p['kg']} kg\n"
                f"   💰 {p['price']:,.0f} so‘m/kg\n"
                f"   📉 Skidka: {p['skidka_pct']}%\n"
                f"   ↩️ Vozvrat: {p['vozvrat_kg']} kg\n"
                f"   💵 {p['payable']:,.0f} so‘m\n\n"
            )

        await update.message.reply_text(
            "📋 YUKNI TASDIQLASH\n\n"
            f"🚚 Mashina: {x['vehicle']}\n"
            f"👤 Ism: {x['name']}\n\n"
            f"{details}"
            f"⚖️ JAMI: {total_weight} kg\n"
            f"↩️ VOZVRAT: {total_return} kg\n"
            f"💵 JAMI TO‘LOV: {total_payable:,.0f} so‘m\n\n"
            "Saqlaymizmi?",
            reply_markup=confirm_keyboard(),
        )
        return 11

    return 9

async def load_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != YES:
        return 11

    x = context.user_data.get("load", {})
    pool = context.application.bot_data.get(DB_KEY)

    if pool is None:
        await update.message.reply_text(
            "❗ PostgreSQL ulanmagan. Yuk saqlanmadi.",
            reply_markup=menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        load_items = [
            {
                "material": p["material"],
                "kg": p["kg"],
                "price": p["price"],
                "skidka_pct": p["skidka_pct"],
                "vozvrat_kg": p["vozvrat_kg"],
            }
            for p in x["products"]
        ]
        load_no_id = await db.create_load(
            pool,
            __import__("datetime").date.today(),
            x["vehicle"],
            x["name"],
            load_items,
        )
        load_no = load_no_id[1] if isinstance(load_no_id, tuple) else load_no_id

        await update.message.reply_text(
            f"✅ Yuk qabul qilindi!\n\n"
            f"🔢 Yuk №{load_no}\n"
            f"🚚 Mashina: {x['vehicle']}\n"
            f"👤 {x['name']}\n"
            f"⚖️ Jami: {sum(p['kg'] for p in x['products'])} kg",
            reply_markup=menu_keyboard(),
        )
    except Exception:
        logger.exception("Load save failed")
        await update.message.reply_text(
            "❗ Yukni saqlashda xatolik yuz berdi.",
            reply_markup=menu_keyboard(),
        )

    context.user_data.clear()
    return ConversationHandler.END

async def load_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❗ Hozircha tuzatish uchun yukni qaytadan kiritish kerak.",
        reply_markup=cancel_keyboard(),
    )
    return 10

# ---------------- QOZON ----------------

async def furnace_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Qozonni tanlang:",
        reply_markup=ReplyKeyboardMarkup(
            [["🔥 Mis qozon"], ["🔥 Latun qozon"], ["🔥 Alyumin qozon"], [CANCEL]],
            resize_keyboard=True,
        ),
    )
    return 20

async def furnace_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["furnace_kind"] = update.message.text
    await update.message.reply_text(
        "📦 Material nomini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 21

async def furnace_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["furnace_material"] = update.message.text.strip()
    await update.message.reply_text(
        "⚖️ Kg miqdorini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 22

async def furnace_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        kg = Decimal(update.message.text.replace(",", "."))
        if kg <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("❗ Kg ni to‘g‘ri kiriting.")
        return 22

    context.user_data["furnace_kg"] = kg
    await update.message.reply_text(
        f"📋 Tekshiring:\n\n"
        f"🔥 {context.user_data['furnace_kind']}\n"
        f"📦 {context.user_data['furnace_material']}\n"
        f"⚖️ {kg} kg\n\n"
        "Saqlaymizmi?",
        reply_markup=confirm_keyboard(),
    )
    return 23

async def furnace_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == NO:
        await update.message.reply_text(
            "❌ Saqlanmadi. Materialni qaytadan kiriting:",
            reply_markup=cancel_keyboard(),
        )
        return 21

    if update.message.text != YES:
        return 23

    pool = context.application.bot_data.get(DB_KEY)
    if pool is None:
        await update.message.reply_text(
            "❗ PostgreSQL ulanmagan. Saqlanmadi.",
            reply_markup=menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        await db.create_furnace(
            pool,
            __import__("datetime").date.today(),
            context.user_data["furnace_kind"],
            [{
                "material": context.user_data["furnace_material"],
                "kg": context.user_data["furnace_kg"],
            }],
        )
        await update.message.reply_text("✅ Qozonga berish saqlandi.", reply_markup=menu_keyboard())
    except Exception as exc:
        await update.message.reply_text(f"❗ {exc}", reply_markup=menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# ---------------- ASOSIY BO‘LIMLAR ----------------

async def raw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.application.bot_data.get(DB_KEY)
    if pool is None:
        await update.message.reply_text("❗ PostgreSQL ulanmagan.", reply_markup=menu_keyboard())
        return

    rows = await db.raw_stock(pool)
    if not rows:
        text = "📦 Xomashyo ombori bo‘sh."
    else:
        text = "📦 XOMASHYO OMBORI\n\n"
        for r in rows:
            text += f"• {r['material']}: {r['kg']:g} kg\n"

    await update.message.reply_text(text, reply_markup=menu_keyboard())

async def finished_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.application.bot_data.get(DB_KEY)
    if pool is None:
        await update.message.reply_text("❗ PostgreSQL ulanmagan.", reply_markup=menu_keyboard())
        return
    rows = await db.finished_stock(pool)
    text = "🏭 TAYYOR MAHSULOT\n\n"
    if rows:
        for r in rows:
            text += f"• {r['product']}: {r['kg']:g} kg\n"
    else:
        text += "Ombor bo‘sh."
    await update.message.reply_text(text, reply_markup=menu_keyboard())

async def scrap_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.application.bot_data.get(DB_KEY)
    if pool is None:
        await update.message.reply_text("❗ PostgreSQL ulanmagan.", reply_markup=menu_keyboard())
        return
    rows = await db.scrap_stock(pool)
    text = "♻️ CHIQIT OMBORI\n\n"
    if rows:
        for r in rows:
            text += f"• {r['scrap_type']}: {r['kg']:g} kg\n"
    else:
        text += "Ombor bo‘sh."
    await update.message.reply_text(text, reply_markup=menu_keyboard())

async def sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Sotuv bo‘limi.", reply_markup=menu_keyboard())

async def report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.application.bot_data.get(DB_KEY)
    if pool is None:
        await update.message.reply_text("❗ PostgreSQL ulanmagan.", reply_markup=menu_keyboard())
        return
    today = __import__("datetime").date.today()
    r = await db.report(pool, today, today)
    await update.message.reply_text(
        "📊 UMUMIY HISOB — BUGUN\n\n"
        f"📥 Yuklar: {r['loads']} ta\n"
        f"⚖️ Kirim: {r['incoming_kg']:g} kg\n"
        f"💰 Sotuv: {r['revenue']:,.0f} so‘m\n"
        f"⚙️ Xarajat: {r['expenses']:,.0f} so‘m",
        reply_markup=menu_keyboard(),
    )

async def expenses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Xarajatlar bo‘limi.", reply_markup=menu_keyboard())

# ---------------- REGISTER ----------------

def register_handlers(application: Application):
    load_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📥 Yuk qabul qilish$"), load_start)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_vehicle)],
            2: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_name)],
            3: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_product)],
            4: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_custom_product)],
            5: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_weight)],
            6: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_price)],
            7: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_discount)],
            8: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_return)],
            9: [MessageHandler(filters.Regex("^➕ Yana mahsulot$|^✅ Ha$|^❌ Yo‘q$"), load_after_product)],
            10: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), load_correction)],
            11: [MessageHandler(filters.Regex(f"^{YES}$"), load_save)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
    )

    furnace_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔥 Qozonga berilgan mahsulotlar$"), furnace_start)],
        states={
            20: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), furnace_kind)],
            21: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), furnace_material)],
            22: [MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"), furnace_weight)],
            23: [MessageHandler(filters.Regex(f"^{YES}$|^{NO}$"), furnace_confirm)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(load_conv)
    application.add_handler(furnace_conv)

    application.add_handler(MessageHandler(filters.Regex("^🏭 Tayyor mahsulot$"), finished_menu))
    application.add_handler(MessageHandler(filters.Regex("^♻️ Chiqit ombori$"), scrap_menu))
    application.add_handler(MessageHandler(filters.Regex("^📦 Xomashyo ombori$"), raw_menu))
    application.add_handler(MessageHandler(filters.Regex("^💰 Sotuv$"), sales_menu))
    application.add_handler(MessageHandler(filters.Regex("^📊 Umumiy hisob$"), report_menu))
    application.add_handler(MessageHandler(filters.Regex("^⚙️ Xarajatlar$"), expenses_menu))
    application.add_handler(MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel))

def set_bot_commands(application: Application):
    async def setup_commands(app: Application):
        await app.bot.set_my_commands([("start", "Botni boshlash")])
    application.post_init = setup_commands

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
