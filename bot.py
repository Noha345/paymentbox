import asyncio
import io
import logging
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

# -------------------------------------------------
# ENV
# -------------------------------------------------
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
PORT = int(os.getenv("PORT", 8080))

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# DB
# -------------------------------------------------
settings_col = None
users_col = None

if MONGO_URL:
    try:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["VipBotDB"]
        settings_col = db["settings"]
        users_col = db["users"]
        logging.info("MongoDB connected")
    except Exception as e:
        logging.error(f"Mongo error: {e}")

# -------------------------------------------------
# BOT
# -------------------------------------------------
bot = Bot(token=TOKEN) if TOKEN else None
dp = Dispatcher(storage=MemoryStorage()) if TOKEN else None

# -------------------------------------------------
# CONSTANTS
# -------------------------------------------------
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
    }
}

# -------------------------------------------------
# FSM
# -------------------------------------------------
class UserState(StatesGroup):
    waiting_for_proof = State()

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
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

# -------------------------------------------------
# WEB SERVER (Render keep-alive)
# -------------------------------------------------
async def health(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# -------------------------------------------------
# HANDLERS
# -------------------------------------------------
if dp:

    @dp.message(CommandStart())
    async def start_cmd(message: types.Message):
        if users_col:
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
            f"👋 Hello {message.from_user.first_name}",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=kb, resize_keyboard=True
            )
        )

    @dp.message(F.text == "💎 Buy VIP Membership")
    async def show_categories(message: types.Message):
        settings = await get_settings()
        if not settings:
            return await message.answer("Temporary issue. Try later.")

        builder = InlineKeyboardBuilder()
        for k, v in settings["categories"].items():
            builder.button(
                text=f"{v['name']} ({v['price']})",
                callback_data=f"cat:{k}"
            )
        builder.adjust(1)

        await message.answer(
            "Select a category:",
            reply_markup=builder.as_markup()
        )

    @dp.callback_query(F.data.startswith("cat:"))
    async def choose_category(cb: types.CallbackQuery, state: FSMContext):
        key = cb.data.split(":")[1]
        settings = await get_settings()
        cat = settings["categories"].get(key)

        if not cat:
            return await cb.answer("Not found", show_alert=True)

        await state.update_data(category=key)
        await state.set_state(UserState.waiting_for_proof)

        qr = generate_upi_qr(settings["upi_id"])
        await cb.message.answer_photo(
            types.BufferedInputFile(qr.getvalue(), "upi.png"),
            caption=(
                f"💳 Pay {cat['price']}\n\n"
                f"After payment, send screenshot here."
            )
        )
        await cb.answer()

    @dp.message(UserState.waiting_for_proof)
    async def receive_proof(message: types.Message, state: FSMContext):
        data = await state.get_data()
        cat_key = data.get("category")

        if not cat_key:
            return await message.answer("Session expired.")

        if ADMIN_ID:
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

            if message.photo:
                await bot.send_photo(
                    ADMIN_ID,
                    message.photo[-1].file_id,
                    caption=f"Proof from {message.from_user.id}",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=kb
                    )
                )

        await message.answer("Proof sent. Please wait.")
        await state.clear()

    @dp.callback_query(F.data.startswith("approve:"))
    async def approve(cb: types.CallbackQuery):
        if cb.from_user.id != ADMIN_ID:
            return await cb.answer("Unauthorized", show_alert=True)

        _, user_id, cat_key = cb.data.split(":")
        user_id = int(user_id)

        settings = await get_settings()
        cat = settings["categories"].get(cat_key)

        await bot.send_message(
            user_id,
            f"✅ Approved!\n\n{cat['link']}",
            parse_mode="Markdown"
        )

        await cb.answer("Approved")

    @dp.callback_query(F.data.startswith("reject:"))
    async def reject(cb: types.CallbackQuery):
        if cb.from_user.id != ADMIN_ID:
            return await cb.answer("Unauthorized", show_alert=True)

        user_id = int(cb.data.split(":")[1])
        await bot.send_message(user_id, "❌ Payment rejected.")
        await cb.answer("Rejected")

# -------------------------------------------------
# MAIN
# -------------------------------------------------
async def main():
    await start_web()

    if not bot or not dp:
        while True:
            await asyncio.sleep(3600)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )

if __name__ == "__main__":
    asyncio.run(main())
