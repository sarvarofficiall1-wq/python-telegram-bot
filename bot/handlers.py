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

def menu_keyboard():
    return ReplyKeyboardMarkup(MENU, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[CANCEL]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏭 Zavod hisob botiga xush kelibsiz.",
        reply_markup=menu_keyboard(),
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🚫 Bekor qilindi.",
        reply_markup=menu_keyboard(),
    )
    return ConversationHandler.ENDasync def load_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["load"] = {
        "products": []
    }

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

    keyboard = [
        ["Qizil oddiy", "Qizil Lahim"],
        ["Tros", "Sariq"],
        ["Karbyurator", "Qizil radiator"],
        ["Sariq radiator", "Sink quyma"],
        ["Teplo", "Alyumin zapchast"],
        ["Alyumin chushka", "➕ Boshqa mahsulot"],
        [CANCEL],
    ]

    await update.message.reply_text(
        "📦 Mahsulotni tanlang:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
        ),
    )
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
        f"⚖️ {product}\n\nOg‘irlikni kg da kiriting:",
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
        f"⚖️ {product}\n\nOg‘irlikni kg da kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 5async def load_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = Decimal(update.message.text.replace(",", "."))
        if weight <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❗ Kg ni to‘g‘ri kiriting.\nMasalan: 1000 yoki 1031.5"
        )
        return 5

    context.user_data["load"]["current_weight"] = weight

    await update.message.reply_text(
        "💰 1 kg narxini so‘mda kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 6


async def load_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = Decimal(
            update.message.text.replace(" ", "").replace(",", ".")
        )
        if price < 0:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❗ Narxni to‘g‘ri kiriting.\nMasalan: 25000"
        )
        return 6

    context.user_data["load"]["current_price"] = price

    await update.message.reply_text(
        "📉 Skidka foizini kiriting.\n"
        "Skidka bo‘lmasa: 0",
        reply_markup=cancel_keyboard(),
    )
    return 7


async def load_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        discount = Decimal(update.message.text.replace(",", "."))
        if discount < 0 or discount > 100:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❗ Skidka 0 dan 100 gacha bo‘lishi kerak."
        )
        return 7

    context.user_data["load"]["current_discount"] = discount

    await update.message.reply_text(
        "↩️ Vozvrat kg ni kiriting.\n"
        "Vozvrat bo‘lmasa: 0",
        reply_markup=cancel_keyboard(),
    )
    return 8


async def load_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        returned = Decimal(update.message.text.replace(",", "."))
        weight = context.user_data["load"]["current_weight"]

        if returned < 0 or returned > weight:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❗ Vozvrat kg miqdorini to‘g‘ri kiriting."
        )
        return 8

    x = context.user_data["load"]

    product = x["current_product"]
    weight = x["current_weight"]
    price = x["current_price"]
    discount = x["current_discount"]

    payable_kg = weight - returned
    payable = (
        payable_kg
        * price
        * (Decimal("100") - discount)
        / Decimal("100")
    )

    x["products"].append({
        "product": product,
        "weight": weight,
        "price": price,
        "discount": discount,
        "returned": returned,
        "payable": payable,
    })

    total_weight = sum(
        item["weight"] for item in x["products"]
    )

    total_payable = sum(
        item["payable"] for item in x["products"]
    )

    await update.message.reply_text(
        f"✅ {product} qo‘shildi.\n\n"
        f"⚖️ Kg: {weight} kg\n"
        f"💰 Narx: {price} so‘m/kg\n"
        f"📉 Skidka: {discount}%\n"
        f"↩️ Vozvrat: {returned} kg\n"
        f"💵 To‘lanadi: {payable:,.0f} so‘m\n\n"
        f"📦 Jami yuk: {total_weight} kg\n"
        f"💵 Jami to‘lov: {total_payable:,.0f} so‘m",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["➕ Yana mahsulot"],
                [YES, NO],
                [CANCEL],
            ],
            resize_keyboard=True,
        ),
    )

    return 9async def load_after_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "➕ Yana mahsulot":
        keyboard = [
            ["Qizil oddiy", "Qizil Lahim"],
            ["Tros", "Sariq"],
            ["Karbyurator", "Qizil radiator"],
            ["Sariq radiator", "Sink quyma"],
            ["Teplo", "Alyumin zapchast"],
            ["Alyumin chushka", "➕ Boshqa mahsulot"],
            [CANCEL],
        ]

        await update.message.reply_text(
            "📦 Keyingi mahsulotni tanlang:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard,
                resize_keyboard=True,
            ),
        )
        return 3

    if text == NO:
        await update.message.reply_text(
            "Qaysi ma’lumotni tuzatamiz?\n\n"
            "🚚 Mashina raqami\n"
            "👤 Ismi familiyasi\n"
            "📦 Mahsulot\n"
            "⚖️ Kg\n"
            "💰 Narx\n"
            "📉 Skidka\n"
            "↩️ Vozvrat",
            reply_markup=cancel_keyboard(),
        )
        return 10

    if text == YES:
        x = context.user_data["load"]

        total_weight = sum(
            item["weight"] for item in x["products"]
        )

        total_return = sum(
            item["returned"] for item in x["products"]
        )

        total_payable = sum(
            item["payable"] for item in x["products"]
        )

        products_text = ""

        for i, item in enumerate(x["products"], 1):
            products_text += (
                f"{i}. 📦 {item['product']}\n"
                f"   ⚖️ {item['weight']} kg\n"
                f"   💰 {item['price']:,.0f} so‘m/kg\n"
                f"   📉 Skidka: {item['discount']}%\n"
                f"   ↩️ Vozvrat: {item['returned']} kg\n"
                f"   💵 To‘lov: {item['payable']:,.0f} so‘m\n\n"
            )

        await update.message.reply_text(
            "📋 YUKNI TASDIQLASH\n\n"
            f"🚚 Mashina: {x['vehicle']}\n"
            f"👤 Ism familiya: {x['name']}\n\n"
            f"{products_text}"
            f"⚖️ JAMI: {total_weight} kg\n"
            f"↩️ JAMI VOZVRAT: {total_return} kg\n"
            f"💵 JAMI TO‘LOV: {total_payable:,.0f} so‘m\n\n"
            "Saqlaymizmi?",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [YES, NO],
                    [CANCEL],
                ],
                resize_keyboard=True,
            ),
        )
        return 11

    return 9


async def load_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != YES:
        return 11

    x = context.user_data.get("load", {})

    # Keyingi qismda PostgreSQL ga haqiqiy saqlash,
    # global yuk raqami va xomashyo omboriga qo‘shish ulanadi.

    total_weight = sum(
        item["weight"] for item in x.get("products", [])
    )

    await update.message.reply_text(
        "✅ Yuk qabul qilindi!\n\n"
        f"🚚 Mashina: {x.get('vehicle', '-')}\n"
        f"👤 {x.get('name', '-')}\n"
        f"⚖️ Jami: {total_weight} kg\n\n"
        "🏠 Bosh menyu",
        reply_markup=menu_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.ENDasync def furnace_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Qozonni tanlang:",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["🔥 Mis qozon"],
                ["🔥 Latun qozon"],
                ["🔥 Alyumin qozon"],
                [CANCEL],
            ],
            resize_keyboard=True,
        ),
    )
    return 20


async def furnace_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["furnace_kind"] = update.message.text

    await update.message.reply_text(
        "📦 Materialni tanlang yoki nomini yozing:",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["Qizil", "Qizil Lahim"],
                ["Tros", "Sariq"],
                ["Karbyurator", "Qizil radiator"],
                ["Sariq radiator", "Sink quyma"],
                ["Alyumin zapchast", "Alyumin chushka"],
                ["➕ Boshqa material"],
                [CANCEL],
            ],
            resize_keyboard=True,
        ),
    )
    return 21


async def furnace_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    material = update.message.text.strip()

    if material == "➕ Boshqa material":
        await update.message.reply_text(
            "📦 Material nomini yozing:",
            reply_markup=cancel_keyboard(),
        )
        return 22

    context.user_data["furnace_material"] = material

    await update.message.reply_text(
        f"⚖️ {material}\n\nKg miqdorini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 23


async def furnace_custom_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["furnace_material"] = update.message.text.strip()

    await update.message.reply_text(
        "⚖️ Kg miqdorini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    return 23


async def furnace_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = Decimal(update.message.text.replace(",", "."))
        if weight <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❗ Kg ni to‘g‘ri kiriting.\nMasalan: 100 yoki 1031.5"
        )
        return 23

    context.user_data["furnace_weight"] = weight

    await update.message.reply_text(
        "📋 Tekshiring:\n\n"
        f"🔥 Qozon: {context.user_data['furnace_kind']}\n"
        f"📦 Material: {context.user_data['furnace_material']}\n"
        f"⚖️ Miqdor: {weight} kg\n\n"
        "Saqlaymizmi?",
        reply_markup=ReplyKeyboardMarkup(
            [
                [YES, NO],
                [CANCEL],
            ],
            resize_keyboard=True,
        ),
    )
    return 24


async def furnace_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == NO:
        await update.message.reply_text(
            "❌ Saqlanmadi.\nMaterialni qaytadan kiriting:",
            reply_markup=cancel_keyboard(),
        )
        return 21

    if update.message.text != YES:
        return 24

    await update.message.reply_text(
        "✅ Qozonga berish saqlandi.",
        reply_markup=menu_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.END


async def simple_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    messages = {
        "🏭 Tayyor mahsulot":
            "🏭 Tayyor mahsulot bo‘limi",
        "♻️ Chiqit ombori":
            "♻️ Chiqit ombori bo‘limi",
        "📦 Xomashyo ombori":
            "📦 Xomashyo ombori bo‘limi",
        "💰 Sotuv":
            "💰 Sotuv bo‘limi",
        "📊 Umumiy hisob":
            "📊 Umumiy hisob bo‘limi",
        "⚙️ Xarajatlar":
            "⚙️ Xarajatlar bo‘limi",
    }

    await update.message.reply_text(
        messages.get(text, "Bo‘lim tanlandi."),
        reply_markup=menu_keyboard(),def register_handlers(application: Application):

    load_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^📥 Yuk qabul qilish$"),
                load_start
            )
        ],
        states={
            1: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_vehicle
                )
            ],
            2: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_name
                )
            ],
            3: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_product
                )
            ],
            4: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_custom_product
                )
            ],
            5: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_weight
                )
            ],
            6: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_price
                )
            ],
            7: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_discount
                )
            ],
            8: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_return
                )
            ],
            9: [
                MessageHandler(
                    filters.Regex("^➕ Yana mahsulot$|^✅ Ha$|^❌ Yo‘q$"),
                    load_after_product
                )
            ],
            10: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    load_correction
                )
            ],
            11: [
                MessageHandler(
                    filters.Regex(f"^{YES}$"),
                    load_save
                )
            ],
        },
        fallbacks=[
            MessageHandler(
                filters.Regex(f"^{CANCEL}$"),
                cancel
            )
        ],
    )

    furnace_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^🔥 Qozonga berilgan mahsulotlar$"),
                furnace_start
            )
        ],
        states={
            20: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    furnace_kind
                )
            ],
            21: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    furnace_material
                )
            ],
            22: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    furnace_custom_material
                )
            ],
            23: [
                MessageHandler(
                    filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),
                    furnace_weight
                )
            ],
            24: [
                MessageHandler(
                    filters.Regex(f"^{YES}$|^{NO}$"),
                    furnace_confirm
                )
            ],
        },
        fallbacks=[
            MessageHandler(
                filters.Regex(f"^{CANCEL}$"),
                cancel
            )
        ],
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(load_conv)

    application.add_handler(furnace_conv)

    application.add_handler(
        MessageHandler(
            filters.Regex(
                "^(🏭 Tayyor mahsulot|"
                "♻️ Chiqit ombori|"
                "📦 Xomashyo ombori|"
                "💰 Sotuv|"
                "📊 Umumiy hisob|"
                "⚙️ Xarajatlar)$"
            ),
            simple_menu
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{CANCEL}$"),
            cancel
        )
    )


def set_bot_commands(application: Application):
    async def setup_commands(app: Application):
        await app.bot.set_my_commands([
            ("start", "Botni boshlash"),
        ])

    application.post_init = setup_commands


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.error(
        "Unhandled exception: %s",
        context.error,
        exc_info=context.error,
    )
    
