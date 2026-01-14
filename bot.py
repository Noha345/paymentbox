import logging
import asyncio
import io
import os
import sys

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
# ENVIRONMENT CONFIGURATION
# =================================================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
# Render provides the PORT automatically
PORT = int(os.getenv("PORT", 8080))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# Admin ID handling
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

# Logger setup
logging.basicConfig(level=logging.INFO)

# =================================================
# DATABASE SETUP
# =================================================
settings_col = None
users_col = None

async def init_db():
    global settings_col, users_col
    if not MONGO_URL:
        logging.error("❌ MONGO_URL is missing! Database features will fail.")
        return

    try:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["VipBotDB"]
        settings_col = db["settings"]
        users_col = db["users"]
        # Test connection
        await client.admin.command('ping')
        logging.info("✅ MongoDB Connected Successfully")
    except Exception as e:
        logging.error(f"❌ Database Connection Error: {e}")

# =================================================
# BOT SETUP
# =================================================
if not TOKEN:
    logging.critical("❌ BOT_TOKEN is missing! The bot cannot start.")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =================================================
# DEFAULT SETTINGS
# =================================================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/example"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/example"},
    "coding": {"name": "💻 Coding Courses", "price": "199 INR", "link": "https://t.me/example"},
    "gaming": {"name": "🎮 Gaming Mods", "price": "149 INR", "link": "https://t.me/example"}
}

# =================================================
# FSM STATES
# =================================================
class UserState(StatesGroup):
    waiting_for_proof = State()

# =================================================
# HELPER FUNCTIONS
# =================================================
async def get_settings():
    """Fetches settings or creates defaults if missing."""
    if settings_col is None:
        return None

    try:
        settings = await settings_col.find_one({"_id": "main"})
        if not settings:
            settings = {
                "_id": "main",
                "upi_id": "nohasheldendsouza@oksbi", # CHANGE THIS TO YOUR UPI
                "categories": DEFAULT_CATEGORIES
            }
            await settings_col.insert_one(settings)
            logging.info("⚙️ Default settings created in Database.")
        return settings
    except Exception as e:
        logging.error(f"Error fetching settings: {e}")
        return None

def generate_upi_qr(upi_id: str) -> io.BytesIO:
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP&cu=INR"
    qr = qrcode.make(upi_url)
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

# =================================================
# WEB SERVER (REQUIRED FOR RENDER)
# =================================================
async def health_check(request):
    return web.Response(text="Bot is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"🌍 Web Server running on port {PORT}")

# =================================================
# BOT HANDLERS
# =================================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    # Safe DB update
    if users_col is not None:
        try:
            await users_col.update_one(
                {"user_id": message.from_user.id},
                {"$set": {"username": message.from_user.username}},
                upsert=True
            )
        except Exception as e:
            logging.error(f"DB Error on start: {e}")

    kb = [[
        types.KeyboardButton(text="💎 Buy VIP Membership"),
        types.KeyboardButton(text="🆘 Support")
    ]]
    
    await message.answer(
        f"👋 Hello {message.from_user.first_name}!\n\nWelcome to the VIP Store.",
        reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def show_categories(message: types.Message):
    settings = await get_settings()
    
    # If DB is down or settings failed
    if not settings:
        return await message.answer("⚠️ System is initializing or Database is down. Try again in 1 minute.")

    builder = InlineKeyboardBuilder()
    for k, v in settings["categories"].items():
        builder.button(text=f"{v['name']} — {v['price']}", callback_data=f"cat:{k}")
    builder.adjust(1)

    await message.answer("✨ Choose a VIP Category:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("cat:"))
async def choose_category(cb: types.CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    settings = await get_settings()
    
    if not settings or key not in settings["categories"]:
        return await cb.answer("Category not found", show_alert=True)

    cat = settings["categories"][key]
    await state.update_data(category=key)

    qr = generate_upi_qr(settings["upi_id"])
    
    await cb.message.answer_photo(
        types.BufferedInputFile(qr.getvalue(), "upi.png"),
        caption=(
            f"💳 **Category:** {cat['name']}\n"
            f"💰 **Price:** {cat['price']}\n\n"
            f"1️⃣ Scan the QR to pay.\n"
            f"2️⃣ Send the screenshot here."
        ),
        parse_mode="Markdown"
    )
    await state.set_state(UserState.waiting_for_proof)
    await cb.answer()

@dp.message(UserState.waiting_for_proof)
async def receive_proof(message: types.Message, state: FSMContext):
    if not message.photo:
        return await message.answer("⚠️ Please send a photo/screenshot of the payment.")

    data = await state.get_data()
    cat_key = data.get("category")
    settings = await get_settings()
    cat = settings["categories"].get(cat_key)

    # Admin Buttons
    kb = [[
        types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{message.from_user.id}:{cat_key}"),
        types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{message.from_user.id}")
    ]]

    if ADMIN_ID != 0:
        await bot.send_photo(
            ADMIN_ID,
            message.photo[-1].file_id,
            caption=(
                f"🧾 **New Payment Proof**\n"
                f"👤 User: {message.from_user.id}\n"
                f"📦 Plan: {cat['name']}\n"
                f"💰 Price: {cat['price']}"
            ),
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb),
            parse_mode="Markdown"
        )
        await message.answer("✅ **Proof Sent!** Please wait for admin approval.")
    else:
        await message.answer("⚠️ Admin ID not set. Proof received but cannot forward.")

    await state.clear()

@dp.callback_query(F.data.startswith("approve:"))
async def approve(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return await cb.answer("Unauthorized", show_alert=True)

    _, user_id, cat_key = cb.data.split(":")
    user_id = int(user_id)
    settings = await get_settings()
    cat = settings["categories"].get(cat_key)

    try:
        await bot.send_message(
            user_id,
            f"✅ **Payment Approved!**\n\nHere is your link:\n{cat['link']}",
            parse_mode="Markdown"
        )
        await cb.message.edit_caption(caption=cb.message.caption + "\n\n✅ **APPROVED**")
    except Exception as e:
        await cb.answer(f"Error: {e}", show_alert=True)

    await cb.answer("Approved")

@dp.callback_query(F.data.startswith("reject:"))
async def reject(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return await cb.answer("Unauthorized", show_alert=True)

    user_id = int(cb.data.split(":")[1])
    try:
        await bot.send_message(user_id, "❌ **Payment Rejected.** Contact support.")
        await cb.message.edit_caption(caption=cb.message.caption + "\n\n❌ **REJECTED**")
    except Exception:
        pass

    await cb.answer("Rejected")

# =================================================
# MAIN ENTRY POINT
# =================================================
async def main():
    # 1. Connect to Database
    await init_db()
    
    # 2. Start Web Server (Keep Render Alive)
    await start_web_server()

    # 3. Start Bot Polling
    logging.info("🚀 Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
        
        
