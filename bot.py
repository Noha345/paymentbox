import logging
import asyncio
import io
import os
import sys
import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
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
PORT = int(os.getenv("PORT", 8080))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "1234")  # Default password if not set

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
purchases_col = None  # New collection for purchase history

async def init_db():
    global settings_col, users_col, purchases_col
    if not MONGO_URL:
        logging.error("❌ MONGO_URL is missing! Database features will fail.")
        return

    try:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["VipBotDB"]
        settings_col = db["settings"]
        users_col = db["users"]
        purchases_col = db["purchases"] # Store purchase history here
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
    waiting_for_password = State() # State for locking the bot
    waiting_for_proof = State()
    choosing_payment_method = State() # State to choose UPI, PayPal, or Bank

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
                "upi_id": "nohasheldendsouza@oksbi", 
                "paypal_link": "https://paypal.me/yourusername", # Default PayPal
                "bank_details": "Bank Name: SBI\nAcc No: 1234567890\nIFSC: SBIN0001234", # Default Bank
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

async def is_user_unlocked(user_id: int) -> bool:
    """Checks if the user has entered the correct password."""
    if users_col is None: return False
    user = await users_col.find_one({"user_id": user_id})
    return user and user.get("is_unlocked", False)

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
# BOT HANDLERS - AUTHENTICATION
# =================================================

@dp.message(Command("login"))
async def login_cmd(message: types.Message, state: FSMContext):
    await message.answer("🔒 Please enter the bot password to access:")
    await state.set_state(UserState.waiting_for_password)

@dp.message(UserState.waiting_for_password)
async def check_password(message: types.Message, state: FSMContext):
    if message.text == BOT_PASSWORD:
        if users_col is not None:
             await users_col.update_one(
                {"user_id": message.from_user.id},
                {"$set": {"is_unlocked": True, "username": message.from_user.username}},
                upsert=True
            )
        await message.answer("✅ Password Correct! You now have access.\nType /start to begin.")
        await state.clear()
    else:
        await message.answer("❌ Incorrect Password. Try again or type /login to restart.")

# Check for access before every other command
async def check_access_middleware(message: types.Message):
    if not await is_user_unlocked(message.from_user.id):
        await message.answer("🔒 This bot is password protected.\nType /login to enter the password.")
        return False
    return True

# =================================================
# BOT HANDLERS - MAIN
# =================================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    # Check Access
    if not await check_access_middleware(message): return

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
    if not await check_access_middleware(message): return
    
    settings = await get_settings()
    if not settings:
        return await message.answer("⚠️ System is initializing. Try again in 1 minute.")

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

    # Ask for Payment Method
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇳 UPI (QR Code)", callback_data="pay:upi")
    builder.button(text="🌍 PayPal", callback_data="pay:paypal")
    builder.button(text="🏦 Bank Transfer", callback_data="pay:bank")
    builder.adjust(1)

    await cb.message.edit_text(
        f"**Selected Plan:** {cat['name']}\n"
        f"**Price:** {cat['price']}\n\n"
        f"💳 Please select a payment method:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await state.set_state(UserState.choosing_payment_method)

@dp.callback_query(F.data.startswith("pay:"))
async def send_payment_details(cb: types.CallbackQuery, state: FSMContext):
    method = cb.data.split(":")[1]
    settings = await get_settings()
    
    text = ""
    photo = None
    
    if method == "upi":
        qr = generate_upi_qr(settings["upi_id"])
        photo = types.BufferedInputFile(qr.getvalue(), "upi.png")
        text = f"**Pay via UPI**\nUPI ID: `{settings['upi_id']}`\n\nScan the QR code to pay."
        
    elif method == "paypal":
        text = f"**Pay via PayPal**\nLink: {settings.get('paypal_link', 'Not Available')}\n\nClick the link to pay."
        
    elif method == "bank":
        text = f"**Pay via Bank Transfer**\n\n{settings.get('bank_details', 'Not Available')}\n\nPlease transfer the amount to this account."

    text += "\n\n📸 **After payment, send the screenshot here.**"

    if photo:
        await cb.message.answer_photo(photo, caption=text, parse_mode="Markdown")
    else:
        await cb.message.answer(text, parse_mode="Markdown")

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
                f"👤 User: {message.from_user.id} (@{message.from_user.username})\n"
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
        # 1. Send Link to User
        await bot.send_message(
            user_id,
            f"✅ **Payment Approved!**\n\nHere is your link:\n{cat['link']}",
            parse_mode="Markdown"
        )
        
        # 2. Store Purchase History
        if purchases_col is not None:
            await purchases_col.insert_one({
                "user_id": user_id,
                "category": cat["name"],
                "price": cat["price"],
                "date": datetime.datetime.utcnow(),
                "status": "approved"
            })
            
        await cb.message.edit_caption(caption=cb.message.caption + "\n\n✅ **APPROVED**")
    except Exception as e:
        await cb.answer(f"Error: {e}", show_alert=True)

    await cb.answer("User Notified")

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
    await init_db()
    await start_web_server()
    logging.info("🚀 Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
        
