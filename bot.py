import logging
import asyncio
import io
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import qrcode

# =================================================
# ENVIRONMENT
# =================================================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", f"https://yourdomain.com{WEBHOOK_PATH}")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

logging.basicConfig(level=logging.INFO)

# =================================================
# DATABASE
# =================================================
settings_col = None
users_col = None

if MONGO_URL:
    try:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["VipBotDB"]
        settings_col = db["settings"]
        users_col = db["users"]
        logging.info("✅ MongoDB connected")
    except Exception as e:
        logging.error(f"❌ Mongo error: {e}")

# =================================================
# BOT
# =================================================
bot = Bot(token=TOKEN) if TOKEN else None
dp = Dispatcher(storage=MemoryStorage()) if TOKEN else None

# =================================================
# CATEGORIES
# =================================================
DEFAULT_CATEGORIES = {
    "adult": {
        "name": "🔞 Adult Hub",
        "price": "10 INR",
        "link": "https://t.me/+pDemZzNHnsU5MTg1"
    },
    "movie": {
        "name": "🎬 Movies & Series",
        "price": "100 INR",
        "link": "https://t.me/+ExampleLink"
    },
    "coding": {
        "name": "💻 Coding Courses",
        "price": "199 INR",
        "link": "https://t.me/+ExampleLink"
    },
    "gaming": {
        "name": "🎮 Gaming Mods",
        "price": "149 INR",
        "link": "https://t.me/+ExampleLink"
    },
    "ebooks": {
        "name": "📚 Premium E-Books",
        "price": "99 INR",
        "link": "https://t.me/+ExampleLink"
    },
    "trading": {
        "name": "📈 Trading Signals",
        "price": "299 INR",
        "link": "https://t.me/+ExampleLink"
    }
}

# =================================================
# FSM
# =================================================
class UserState(StatesGroup):
    waiting_for_proof = State()

# =================================================
# HELPERS
# =================================================
async def get_settings():
    if not settings_col:
        return None

    settings = await settings_col.find_one({"_id": "main"})
    if not settings:
        settings = {
            "_id": "main",
            "upi_id": "nohasheldendsouza@oksbi",
            "categories": DEFAULT_CATEGORIES
        }
        await settings_col.insert_one(settings)

    return settings


def generate_upi_qr(upi_id: str) -> io.BytesIO:
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP&cu=INR"
    qr = qrcode.make(upi_url)
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

# =================================================
# WEB SERVER (Webhook + Health)
# =================================================
async def health(request):
    return web.Response(text="Bot is running")

async def webhook_handler(request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# =================================================
# HANDLERS
# =================================================
if dp:

    @dp.message(CommandStart())
    async def start_cmd(message: types.Message):
        if users_col is not None:
            await users_col.update_one(
                {"user_id": message.from_user.id},
                {"$set": {"username": message.from_user.username}},
                upsert=True
            )

        kb = [[
            types.KeyboardButton(text="💎 Buy VIP Membership"),
            types.KeyboardButton(text="🆘 Support")
        ]]

        await message.answer(
            f"👋 Hello {message.from_user.first_name}!\n\nWelcome to the VIP Store.",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=kb, resize_keyboard=True
            )
        )

    @dp.message(F.text == "💎 Buy VIP Membership")
    async def show_categories(message: types.Message):
        settings = await get_settings()
        if not settings:
            return await message.answer("⚠️ Please try again later.")

        builder = InlineKeyboardBuilder()
        for k, v in settings["categories"].items():
            builder.button(
                text=f"{v['name']} — {v['price']}",
                callback_data=f"cat:{k}"
            )

        builder.adjust(2)

        await message.answer(
            "✨ Choose a VIP Category:",
            reply_markup=builder.as_markup()
        )

    @dp.callback_query(F.data.startswith("cat:"))
    async def choose_category(cb: types.CallbackQuery, state: FSMContext):
        key = cb.data.split(":")[1]
        settings = await get_settings()
        cat = settings["categories"].get(key)

        if not cat:
            return await cb.answer("Category not found", show_alert=True)

        await state.update_data(category=key)

        qr = generate_upi_qr(settings["upi_id"])
        await cb.message.answer_photo(
            types.BufferedInputFile(qr.getvalue(), "upi.png"),
            caption=(
                f"💳 **Category:** {cat['name']}\n"
                f"💰 **Price:** {cat['price']}\n\n"
                f"After payment, send screenshot here."
            ),
            parse_mode="Markdown"
        )

        await state.set_state(UserState.waiting_for_proof)
        await cb.answer()

    @dp.message(UserState.waiting_for_proof)
    async def receive_proof(message: types.Message, state: FSMContext):
        data = await state.get_data()
        cat_key = data.get("category")

        settings = await get_settings()
        cat = settings["categories"].get(cat_key)

        kb = [[
            types.InlineKeyboardButton(
                text="✅ Approve",
                callback_data=f"approve:{message.from_user.id}:{cat_key}"
            ),
            types.InlineKeyboardButton(
                text="❌ Reject",
                callback_data=f"reject:{message.from_user.id}"
            )
        ]]

        if ADMIN_ID:
            if message.photo:
                await bot.send_photo(
                    ADMIN_ID,
                    message.photo[-1].file_id,
                    caption=(
                        f"🧾 Payment Proof\n"
                        f"👤 User: {message.from_user.id}\n"
                        f"📦 Category: {cat['name']}\n"
                        f"💰 Price: {cat['price']}"
                    ),
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=kb
                    )
                )
            else:
                await bot.send_message(
                    ADMIN_ID,
                    f"🧾 Text Proof\nUser: {message.from_user.id}",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=kb
                    )
                )

        await message.answer("✅ Proof sent. Please wait for approval.")
        await state.clear()

    @dp.callback_query(F.data.startswith("approve:"))
    async def approve(cb: types.CallbackQuery):
        if cb.from_user.id != ADMIN_ID:
            return await cb.answer("Unauthorized", show_alert=True)

        _, user_id, cat_key = cb.data.split(":")
        user_id = int(user_id)

        settings = await get_settings()
        cat = settings["categories"][cat_key]

        await bot.send_message(
            user_id,
            f"✅ **Payment Approved!**\n\nHere is your access:\n{cat['link']}",
            parse_mode="Markdown"
        )

        await cb.answer("Approved")

    @dp.callback_query(F.data.startswith("reject:"))
    async def reject(cb: types.CallbackQuery):
        if cb.from_user.id != ADMIN_ID:
            return await cb.answer("Unauthorized", show_alert=True)

        user_id = int(cb.data.split(":")[1])
        await bot.send_message(user_id, "❌ Payment rejected. Please contact support.")
        await cb.answer("Rejected")

# =================================================
# MAIN
# =================================================
async def main():
    await start_web()

    if not bot or not dp:
        while True:
            await asyncio.sleep(3600)
