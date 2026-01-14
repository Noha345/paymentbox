import asyncio
import io
import os
import datetime
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode
from dotenv import load_dotenv

# ==========================================
# LOAD ENV
# ==========================================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "1234")

logging.basicConfig(level=logging.INFO)

# ==========================================
# DATABASE
# ==========================================
settings_col = None
users_col = None
purchases_col = None

if MONGO_URL:
    cluster = AsyncIOMotorClient(MONGO_URL)
    db = cluster["VipBotDB"]
    settings_col = db["settings"]
    users_col = db["users"]
    purchases_col = db["purchases"]
    print("✅ MongoDB Connected")
else:
    print("❌ MONGO_URL missing")

# ==========================================
# BOT
# ==========================================
bot = Bot(token=TOKEN) if TOKEN else None
dp = Dispatcher(storage=MemoryStorage()) if TOKEN else None

# ==========================================
# DATA
# ==========================================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/MyAnimeEnglish"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/example"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/example"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/example"},
}

class UserState(StatesGroup):
    awaiting_password = State()
    waiting_for_proof = State()

# ==========================================
# HELPERS
# ==========================================
async def get_settings():
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "nohasheldendsouza@oksbi",
            "paypal_link": "https://paypal.me/yourid",
            "bank_details": "Bank: SBI\nAcc: 123456789\nIFSC: SBIN0001234",
            "categories": DEFAULT_CATEGORIES,
        }
        await settings_col.insert_one(settings)
    return settings

def generate_upi_qr(upi_id: str):
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP_Subscription&cu=INR"
    qr = qrcode.make(upi_url)
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

async def is_user_verified(user_id: int):
    user = await users_col.find_one({"user_id": user_id})
    return bool(user and user.get("verified"))

# ==========================================
# WEB SERVER
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web server started on {PORT}")

# ==========================================
# HANDLERS
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    if await is_user_verified(message.from_user.id):
        await show_main_menu(message)
    else:
        await message.answer("🔒 Enter password:")
        await state.set_state(UserState.awaiting_password)

@dp.message(UserState.awaiting_password)
async def password_check(message: types.Message, state: FSMContext):
    if message.text == BOT_PASSWORD:
        await users_col.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"verified": True, "username": message.from_user.username}},
            upsert=True,
        )
        await state.clear()
        await message.answer("✅ Access granted")
        await show_main_menu(message)
    else:
        await message.answer("❌ Wrong password")

async def show_main_menu(message: types.Message):
    kb = [
        [types.KeyboardButton(text="💎 Buy VIP Membership")],
        [types.KeyboardButton(text="🆘 Support")],
    ]
    await message.answer(
        "👋 Welcome to VIP Store",
        reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True),
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def categories(message: types.Message):
    settings = await get_settings()
    kb = InlineKeyboardBuilder()
    for k, v in settings["categories"].items():
        kb.button(text=f"{v['name']} ({v['price']})", callback_data=f"cat_{k}")
    kb.adjust(1)
    await message.answer("Choose category:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("cat_"))
async def payment_methods(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split("_")[1]
    settings = await get_settings()
    cat = settings["categories"][key]

    await state.update_data(category_key=key, category_name=cat["name"], price=cat["price"])

    buttons = [
        [types.InlineKeyboardButton(text="🇮🇳 UPI", callback_data="pay_upi")],
        [types.InlineKeyboardButton(text="🌍 PayPal", callback_data="pay_paypal")],
        [types.InlineKeyboardButton(text="🏦 Bank", callback_data="pay_bank")],
    ]

    await callback.message.edit_text(
        f"{cat['name']} – {cat['price']}\nSelect payment:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()

@dp.callback_query(F.data.in_({"pay_upi", "pay_paypal", "pay_bank"}))
async def payment_info(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()

    if callback.data == "pay_upi":
        qr = generate_upi_qr(settings["upi_id"])
        await callback.message.answer_photo(
            types.BufferedInputFile(qr.getvalue(), "upi.png"),
            caption=f"UPI ID: `{settings['upi_id']}`",
            parse_mode="Markdown",
        )

    elif callback.data == "pay_paypal":
        await callback.message.answer(settings["paypal_link"])

    else:
        await callback.message.answer(settings["bank_details"])

    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.message(UserState.waiting_for_proof)
async def proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    await message.answer("✅ Proof received, waiting for approval")

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{data['category_key']}")
    kb.button(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
    kb.adjust(2)

    caption = f"User: {message.from_user.id}\nPlan: {data['category_name']}\nPrice: {data['price']}"

    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb.as_markup())
    else:
        await bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("approve_"))
async def approve(callback: types.CallbackQuery):
    _, user_id, cat_key = callback.data.split("_")
    settings = await get_settings()
    link = settings["categories"][cat_key]["link"]

    await bot.send_message(int(user_id), f"✅ Approved!\n{link}")
    await callback.message.edit_caption(callback.message.caption + "\nAPPROVED")
    await callback.answer("Approved")

@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: types.CallbackQuery):
    user_id = callback.data.split("_")[1]
    await bot.send_message(int(user_id), "❌ Payment rejected")
    await callback.message.edit_caption(callback.message.caption + "\nREJECTED")
    await callback.answer("Rejected")

# ==========================================
# MAIN
# ==========================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
