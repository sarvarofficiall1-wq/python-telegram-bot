"""Factory accounting Telegram handlers."""
import logging
from decimal import Decimal, InvalidOperation
from datetime import date

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, ConversationHandler, filters
)
from bot import db

logger = logging.getLogger(__name__)

DB_KEY = "db"

# Main menu
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
    "Alyumin zapchast", "Alyumin chushka", "Qizil skidka",
]
FURNACES = {COPPER: "Mis", BRASS: "Latun", ALUMINUM: "Alyumin"}

MAIN_MENU = ReplyKeyboardMarkup(
    [[ADD_LOAD, COPPER], [BRASS, ALUMINUM], [SALE, STOCK], [REPORT, SEARCH],
     [PROFIT, LOSS]],
    resize_keyboard=True, is_persistent=True, input_field_placeholder="Bo‘limni tanlang"
)
CANCEL_MENU = ReplyKeyboardMarkup([[CANCEL]], resize_keyboard=True)

# Conversation states
(
    LOAD_DATE, LOAD_VEHICLE, LOAD_PERSON, LOAD_MATERIAL, LOAD_KG, LOAD_PRICE,
    LOAD_MORE, LOAD_SKIDKA, LOAD_VOZVRAT,
    FURNACE_DATE, FURNACE_MATERIAL, FURNACE_INPUT, FURNACE_MORE,
    FURNACE_PRODUCT, FURNACE_FINISHED, FURNACE_SCRAP,
    SALE_PRODUCT, SALE_KG, SALE_PRICE, SALE_COST,
    SEARCH_TEXT,
) = range(21)

def _pool(context):
    return context.bot_data.get(DB_KEY)

def _dec(text):
    return Decimal(str(text).replace(" ", "").replace(",", "."))

def _fmt(n):
    d = Decimal(str(n or 0))
    if d == d.to_integral():
        return f"{int(d):,}".replace(",", " ")
    return f"{d:,.2f}".replace(",", " ").replace(".", ",")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        pool = _pool(context)
        if pool:
            await db.upsert_user(pool, user.id, user.username, user.first_name)
    await update.effective_message.reply_text(
        "🏭 Zavod Hisob tizimiga xush kelibsiz!\n\nKerakli bo‘limni tanlang.",
        reply_markup=MAIN_MENU,
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("❌ Bekor qilindi.", reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def add_load_start(update, context):
    context.user_data.clear()
    context.user_data["load_items"] = []
    await update.effective_message.reply_text("📅 Yuk kelgan sanani kiriting (YYYY-MM-DD):", reply_markup=CANCEL_MENU)
    return LOAD_DATE

async def load_date(update, context):
    try:
        d = date.fromisoformat(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text("Sana noto‘g‘ri. Masalan: 2026-09-15")
        return LOAD_DATE
    context.user_data["load_date"] = d.isoformat()
    await update.effective_message.reply_text("🚚 Mashina raqamini kiriting:")
    return LOAD_VEHICLE

async def load_vehicle(update, context):
    context.user_data["vehicle"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("👤 Kimdan / ism-familiya:")
    return LOAD_PERSON

async def load_person(update, context):
    context.user_data["person"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        "📦 Materialni yozing yoki tanlang:\n" + "\n".join(f"• {m}" for m in MATERIALS)
    )
    return LOAD_MATERIAL

async def load_material(update, context):
    text = update.effective_message.text.strip()
    context.user_data["current_material"] = text
    await update.effective_message.reply_text(f"⚖️ {text} — kg miqdorini kiriting:")
    return LOAD_KG

async def load_kg(update, context):
    try:
        kg = _dec(update.effective_message.text)
        if kg <= 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Kg noto‘g‘ri. Masalan: 3000")
        return LOAD_KG
    context.user_data["current_kg"] = kg
    await update.effective_message.reply_text("💵 1 kg narxini kiriting (so‘m):")
    return LOAD_PRICE

async def load_price(update, context):
    try:
        price = _dec(update.effective_message.text)
        if price < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Narx noto‘g‘ri. Masalan: 48000")
        return LOAD_PRICE
    item = {
        "material": context.user_data["current_material"],
        "initial_kg": context.user_data["current_kg"],
        "price": price,
    }
    context.user_data["load_items"].append(item)
    await update.effective_message.reply_text(
        "Material qo‘shildi. Yana material qo‘shasizmi?\n\n"
        "Yana material nomini yozing yoki `yo‘q` deb yozing."
    )
    return LOAD_MORE

async def load_more(update, context):
    text = update.effective_message.text.strip()
    if text.lower() in {"yo‘q", "yoq", "yo'q", "no"}:
        await update.effective_message.reply_text(
            "📉 Skidka kg kiriting (bo‘lmasa 0):"
        )
        return LOAD_SKIDKA
    context.user_data["current_material"] = text
    await update.effective_message.reply_text("⚖️ Kg miqdorini kiriting:")
    return LOAD_KG

async def load_skidka(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Skidka kg noto‘g‘ri. Masalan: 100")
        return LOAD_SKIDKA
    context.user_data["skidka"] = x
    await update.effective_message.reply_text("↩️ Vozvrat kg kiriting (bo‘lmasa 0):")
    return LOAD_VOZVRAT

async def load_vozvrat(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Vozvrat kg noto‘g‘ri. Masalan: 50")
        return LOAD_VOZVRAT
    context.user_data["vozvrat"] = x
    pool = _pool(context)
    if not pool:
        await update.effective_message.reply_text("❌ Baza ulanmagan.", reply_markup=MAIN_MENU)
        return ConversationHandler.END
    load_id = await db.create_load(
        pool, context.user_data["load_date"], context.user_data["vehicle"],
        context.user_data["person"], context.user_data["load_items"],
        context.user_data["skidka"], x,
    )
    summary = await db.get_load(pool, load_id)
    await update.effective_message.reply_text(
        _load_text(summary), reply_markup=MAIN_MENU
    )
    context.user_data.clear()
    return ConversationHandler.END

def _load_text(row):
    lines = [
        "✅ Yuk qabul qilindi",
        f"🚚 Mashina: {row['vehicle_no']}",
        f"👤 Shaxs: {row['person_name']}",
        f"📅 Sana: {row['received_date']}",
    ]
    initial_total = sum(Decimal(str(i["initial_kg"])) * Decimal(str(i["price"])) for i in row["items"])
    total_kg = sum(Decimal(str(i["initial_kg"])) for i in row["items"])
    deductions = Decimal(str(row["skidka_kg"])) + Decimal(str(row["vozvrat_kg"]))
    final_kg = total_kg - deductions
    final_total = Decimal(0)
    for item in row["items"]:
        ikg = Decimal(str(item["initial_kg"]))
        share = (ikg / total_kg) if total_kg else Decimal(0)
        item_deduction = deductions * share
        accepted_item = max(Decimal(0), ikg - item_deduction)
        item_total = accepted_item * Decimal(str(item["price"]))
        final_total += item_total
        lines.append(
            f"\n📦 {item['material']}: {_fmt(ikg)} kg × {_fmt(item['price'])} = "
            f"{_fmt(ikg * Decimal(str(item['price'])))} so‘m"
            f"\n   ✅ Qabul: {_fmt(accepted_item)} kg → {_fmt(item_total)} so‘m"
        )
    diff = final_total - initial_total
    pct = (diff / initial_total * 100) if initial_total else Decimal(0)
    lines += [
        f"\n⚖️ Boshlang‘ich: {_fmt(total_kg)} kg",
        f"📉 Skidka: {_fmt(row['skidka_kg'])} kg",
        f"↩️ Vozvrat: {_fmt(row['vozvrat_kg'])} kg",
        f"✅ Yakuniy qabul: {_fmt(final_kg)} kg",
        f"💰 Boshlang‘ich summa: {_fmt(initial_total)} so‘m",
        f"💰 Yakuniy summa: {_fmt(final_total)} so‘m",
        f"📊 Farq: {_fmt(diff)} so‘m ({_fmt(pct)}%)",
        "📌 Holat: Yakunlandi",
    ]
    return "\n".join(lines)

async def furnace_start(update, context):
    context.user_data.clear()
    context.user_data["furnace_items"] = []
    context.user_data["furnace_type"] = FURNACES[update.effective_message.text]
    await update.effective_message.reply_text("📅 Sana (YYYY-MM-DD):", reply_markup=CANCEL_MENU)
    return FURNACE_DATE

async def furnace_date(update, context):
    try:
        d = date.fromisoformat(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text("Sana noto‘g‘ri. Masalan: 2026-09-15")
        return FURNACE_DATE
    context.user_data["furnace_date"] = d.isoformat()
    await update.effective_message.reply_text("📦 Birinchi material nomini kiriting:")
    return FURNACE_MATERIAL

async def furnace_material(update, context):
    context.user_data["current_material"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("⚖️ Qozonga berilgan kg:")
    return FURNACE_INPUT

async def furnace_input(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x <= 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Kg noto‘g‘ri.")
        return FURNACE_INPUT
    context.user_data["furnace_items"].append(
        {"material": context.user_data["current_material"], "kg": x}
    )
    await update.effective_message.reply_text("Yana material qo‘shasizmi? Nomini yozing yoki `yo‘q`.")
    return FURNACE_MORE

async def furnace_more(update, context):
    text = update.effective_message.text.strip()
    if text.lower() in {"yo‘q", "yoq", "yo'q", "no"}:
        total = sum(i["kg"] for i in context.user_data["furnace_items"])
        context.user_data["input_total"] = total
        await update.effective_message.reply_text(
            f"🔥 Jami kirim: {_fmt(total)} kg\n\n"
            "🏭 Tayyor mahsulot nomini kiriting (masalan: Mis truba, Latun truba, Alyumin uzuk):"
        )
        return FURNACE_PRODUCT
    context.user_data["current_material"] = text
    await update.effective_message.reply_text("⚖️ Shu materialdan qozonga berilgan kg:")
    return FURNACE_INPUT

async def furnace_product(update, context):
    context.user_data["finished_product"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("⚖️ Tayyor mahsulot kg:")
    return FURNACE_FINISHED

async def furnace_finished(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Kg noto‘g‘ri.")
        return FURNACE_FINISHED
    context.user_data["finished"] = x
    await update.effective_message.reply_text("♻️ Chiqit (scrap) kg:")
    return FURNACE_SCRAP

async def furnace_scrap(update, context):
    try:
        scrap = _dec(update.effective_message.text)
        if scrap < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Chiqit kg noto‘g‘ri.")
        return FURNACE_SCRAP
    inp = context.user_data["input_total"]
    fin = context.user_data["finished"]
    loss = inp - fin - scrap
    if loss < 0:
        await update.effective_message.reply_text(
            f"❌ Xato: kirim {_fmt(inp)} kg, tayyor {_fmt(fin)} kg, chiqit {_fmt(scrap)} kg.\n"
            "Kirimdan tayyor+chiqit katta bo‘lishi mumkin emas. Qaytadan kiriting."
        )
        return FURNACE_SCRAP
    pool = _pool(context)
    await db.create_furnace(
        pool, context.user_data["furnace_date"], context.user_data["furnace_type"],
        context.user_data["furnace_items"], fin, scrap
    )
    pct = lambda n: (n / inp * 100) if inp else Decimal(0)
    await update.effective_message.reply_text(
        f"✅ Qozon yozildi\n🔥 {context.user_data['furnace_type']}\n"
        f"📥 Kirim: {_fmt(inp)} kg\n"
        f"📤 Tayyor: {_fmt(fin)} kg ({_fmt(pct(fin))}%)\n"
        f"♻️ Chiqit: {_fmt(scrap)} kg ({_fmt(pct(scrap))}%)\n"
        f"🔻 Yo‘qotish: {_fmt(loss)} kg ({_fmt(pct(loss))}%)\n"
        f"⚖️ Balans: {_fmt(fin + scrap + loss)} kg",
        reply_markup=MAIN_MENU
    )
    context.user_data.clear()
    return ConversationHandler.END

async def sale_start(update, context):
    context.user_data.clear()
    await update.effective_message.reply_text("📦 Sotilgan mahsulot nomi:", reply_markup=CANCEL_MENU)
    return SALE_PRODUCT

async def sale_product(update, context):
    context.user_data["product"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("⚖️ Sotilgan kg:")
    return SALE_KG

async def sale_kg(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x <= 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Kg noto‘g‘ri.")
        return SALE_KG
    context.user_data["sale_kg"] = x
    await update.effective_message.reply_text("💵 Sotuv narxi 1 kg (so‘m):")
    return SALE_PRICE

async def sale_price(update, context):
    try:
        x = _dec(update.effective_message.text)
        if x < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Narx noto‘g‘ri.")
        return SALE_PRICE
    context.user_data["sale_price"] = x
    await update.effective_message.reply_text("📉 Tannarx 1 kg (so‘m):")
    return SALE_COST

async def sale_cost(update, context):
    try:
        cost = _dec(update.effective_message.text)
        if cost < 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("Tannarx noto‘g‘ri.")
        return SALE_COST
    pool = _pool(context)
    kg = context.user_data["sale_kg"]
    price = context.user_data["sale_price"]
    sale_id = await db.create_sale(pool, date.today().isoformat(), context.user_data["product"], kg, price, cost)
    revenue = kg * price
    profit = kg * (price - cost)
    await update.effective_message.reply_text(
        f"✅ Sotuv saqlandi\n📦 {context.user_data['product']}\n"
        f"⚖️ {_fmt(kg)} kg\n💰 Tushum: {_fmt(revenue)} so‘m\n"
        f"🟢 Foyda: {_fmt(profit)} so‘m" if profit >= 0 else
        f"✅ Sotuv saqlandi\n📦 {context.user_data['product']}\n⚖️ {_fmt(kg)} kg\n"
        f"💰 Tushum: {_fmt(revenue)} so‘m\n🔴 Zarar: {_fmt(-profit)} so‘m",
        reply_markup=MAIN_MENU
    )
    context.user_data.clear()
    return ConversationHandler.END

async def stock(update, context):
    pool = _pool(context)
    rows = await db.stock_summary(pool)
    if not rows:
        text = "📦 Ombor hozircha bo‘sh."
    else:
        text = "📦 OMBOR QOLDIG‘I\n\n" + "\n".join(
            f"• {r['material']}: {_fmt(r['kg'])} kg" for r in rows if Decimal(str(r['kg'])) != 0
        )
        if text.endswith("\n\n"): text = "📦 Ombor hozircha bo‘sh."
    await update.effective_message.reply_text(text, reply_markup=MAIN_MENU)

async def report(update, context):
    pool = _pool(context)
    r = await db.report(pool)
    await update.effective_message.reply_text(
        "📊 UMUMIY HISOBOT\n\n"
        f"📦 Jami kirgan: {_fmt(r['incoming_kg'])} kg\n"
        f"📤 Qozonlarga berilgan: {_fmt(r['issued_kg'])} kg\n"
        f"📦 Xomashyo qoldig‘i: {_fmt(r['raw_stock_kg'])} kg\n"
        f"🏭 Tayyor ishlab chiqarilgan: {_fmt(r['finished_kg'])} kg\n"
        f"💰 Tushum: {_fmt(r['revenue'])} so‘m\n"
        f"🟢 Foyda: {_fmt(r['profit'])} so‘m\n"
        f"🔴 Zarar: {_fmt(r['loss'])} so‘m",
        reply_markup=MAIN_MENU
    )

async def profit(update, context):
    pool = _pool(context)
    x = await db.profit_loss(pool)
    await update.effective_message.reply_text(f"🟢 Jami foyda: {_fmt(x)} so‘m", reply_markup=MAIN_MENU)

async def loss(update, context):
    pool = _pool(context)
    x = await db.profit_loss(pool)
    await update.effective_message.reply_text(f"🔴 Jami zarar: {_fmt(-x) if x < 0 else 0} so‘m", reply_markup=MAIN_MENU)

async def search_start(update, context):
    await update.effective_message.reply_text("🔎 Mashina raqami yoki ismni kiriting:", reply_markup=CANCEL_MENU)
    return SEARCH_TEXT

async def search_text(update, context):
    pool = _pool(context)
    rows = await db.search_loads(pool, update.effective_message.text.strip())
    if not rows:
        text = "❌ Topilmadi."
    else:
        text = "🔎 NATIJALAR\n\n" + "\n\n".join(_load_text(r) for r in rows[:5])
    await update.effective_message.reply_text(text, reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def help_command(update, context):
    await update.effective_message.reply_text(
        "📌 /start — asosiy menyu\n"
        "Yuk qabul qilish, qozonlar, sotuv, ombor va hisobot bo‘limlari ishlaydi.",
        reply_markup=MAIN_MENU
    )

async def menu_router(update, context):
    text = update.effective_message.text.strip()
    if text == ADD_LOAD:
        return await add_load_start(update, context)
    if text in FURNACES:
        return await furnace_start(update, context)
    if text == SALE:
        return await sale_start(update, context)
    if text == STOCK:
        await stock(update, context); return ConversationHandler.END
    if text == REPORT:
        await report(update, context); return ConversationHandler.END
    if text == SEARCH:
        return await search_start(update, context)
    if text == PROFIT:
        await profit(update, context); return ConversationHandler.END
    if text == LOSS:
        await loss(update, context); return ConversationHandler.END
    return ConversationHandler.END

async def error_handler(update, context):
    logger.exception("Telegram handler error", exc_info=context.error)

async def set_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands([
        ("start", "Asosiy menyu"),
        ("help", "Yordam"),
    ])

def register_handlers(application: Application) -> None:
    # Each workflow is its own ConversationHandler.
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{ADD_LOAD}$"), add_load_start)],
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
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
        allow_reentry=True,
    ))
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^({COPPER}|{BRASS}|{ALUMINUM})$"), furnace_start)],
        states={
            FURNACE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_date)],
            FURNACE_MATERIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_material)],
            FURNACE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_input)],
            FURNACE_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_more)],
            FURNACE_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_product)],
            FURNACE_FINISHED: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_finished)],
            FURNACE_SCRAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, furnace_scrap)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
        allow_reentry=True,
    ))
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{SALE}$"), sale_start)],
        states={
            SALE_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_product)],
            SALE_KG: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_kg)],
            SALE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_price)],
            SALE_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_cost)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
        allow_reentry=True,
    ))
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{SEARCH}$"), search_start)],
        states={SEARCH_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_text)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"), cancel)],
        allow_reentry=True,
    ))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(
        filters.Regex(f"^({'|'.join(map(lambda s: s.replace('🔥','🔥').replace('➕','➕'), [ADD_LOAD, COPPER, BRASS, ALUMINUM, SALE, STOCK, REPORT, SEARCH, PROFIT, LOSS]))})$"),
        menu_router
    ))
