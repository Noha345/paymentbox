import logging
import asyncio
import io
import os
import sys

# Third-party imports
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

# Load local .env if available
load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================
# ⚠️ SECURITY FIX: Removed hardcoded keys. 
# Set these in your Render Dashboard Environment Variables.
TOKEN = os.getenv("8084906584:AAHTn6qNxYIo46ZXQOonpS4YOBIPU7GThWg")
MONGO_URL = os.getenv("mongodb+srv://paybox:Noha9980@cluster0.xngngqj.mongodb.net/?appName=Cluster0")
# ADMIN_ID needs a default of 0 to prevent crash if env var is missing
ADMIN_ID_STR = os.getenv("ADMIN_ID", "8072674531") 
ADMIN_ID = int(ADMIN_ID_STR)
PORT = int(os.getenv("PORT", 8080))

# ==========================================
# DATABASE SETUP
# ==========================================
if not TOKEN or not MONGO_URL:
    print("⚠️ CRITICAL ERROR: BOT_TOKEN or MONGO_URL is missing.")
    # We do not exit here to keep the Web Server alive on Render,
    # but the bot functionality will fail.

# Initialize DB (Only if URL is present to avoid immediate crash)
if MONGO_URL:
    cluster = AsyncIOMotorClient(MONGO_URL)
    db = cluster["VipBotDB"]
    settings_col = db["settings"]
    users_col = db["users"]

# ==========================================
# BOT SETUP
# ==========================================
if TOKEN:
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
else:
    bot = None
    dp = None

logging.basicConfig(level=logging.INFO)

# ==========================================
# CATEGORIES & LOGIC
# ==========================================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/+ExampleLink"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/+ExampleLink"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/+ExampleLink"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/+ExampleLink"}
}

class UserState(StatesGroup):
    selecting_category = State()
    waiting_for_proof = State()

async def get_settings():
    if not MONGO_URL: return None
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "nohasheldendsouza@oksbi",
            "paypal_link": "paypal.me/example",
            "categories": DEFAULT_CATEGORIES
        }
        await settings_col.insert_one(settings)
    if "categories" not in settings:
        await settings_col.update_one({"_id": "main_settings"}, {"$set": {"categories": DEFAULT_CATEGORIES}})
        settings["categories"] = DEFAULT_CATEGORIES
    return settings

def generate_upi_qr(upi_id):
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP_Subscription&cu=INR"
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ==========================================
# WEB SERVER (REQUIRED FOR RENDER)
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"✅ Web server started on port {PORT}")

# ==========================================
# HANDLERS
# ==========================================
if dp:
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        if users_col:
            await users_col.update_one({"user_id": message.from_user.id}, {"$set": {"username": message.from_user.username}}, upsert=True)
        
        kb = [[types.KeyboardButton(text="💎 Buy VIP Membership"), types.KeyboardButton(text="🆘 Support")]]
        keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        await message.answer(f"👋 **Hello {message.from_user.first_name}!**\n\nWelcome to the Premium Bot.", parse_mode="Markdown", reply_markup=keyboard)

    @dp.message(F.text == "💎 Buy VIP Membership")
    async def show_categories(message: types.Message):
        settings = await get_settings()
        if not settings: return await message.answer("⚠️ Database Error.")
        
        builder = InlineKeyboardBuilder()
        for key, data in settings.get("categories", {}).items():
            builder.button(text=f"{data['name']} ({data['price']})", callback_data=f"cat_{key}")
        builder.adjust(2)
        await message.answer("✨ **VIP Access Hub** ✨\nSelect a category:", parse_mode="Markdown", reply_markup=builder.as_markup())

    @dp.callback_query(F.data.startswith("cat_"))
    async def process_category_selection(callback: types.CallbackQuery, state: FSMContext):
        cat_key = callback.data.split("_")[1]
        settings = await get_settings()
        category = settings["categories"].get(cat_key)
        if not category: return await callback.answer("Category not found.", show_alert=True)
        
        await state.update_data(selected_category=cat_key, price=category['price'], cat_name=category['name'])
        kb = [[types.InlineKeyboardButton(text="🇮🇳 Pay via UPI", callback_data="pay_upi")]]
        await callback.message.edit_text(f"💎 **Selected:** {category['name']}\n💰 **Price:** {category['price']}", parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

    @dp.callback_query(F.data == "pay_upi")
    async def process_upi_pay(callback: types.CallbackQuery, state: FSMContext):
        settings = await get_settings()
        qr_bio = generate_upi_qr(settings.get('upi_id'))
        await callback.message.answer_photo(types.BufferedInputFile(qr_bio.getvalue(), filename="qr.png"), caption="Scan to Pay & Send Proof")
        await state.set_state(UserState.waiting_for_proof)
        await callback.answer()

    @dp.message(UserState.waiting_for_proof)
    async def handle_proof(message: types.Message, state: FSMContext):
        data = await state.get_data()
        if not data:
            await message.answer("❌ Session expired. Please try again.")
            return

        kb = [[types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{data['selected_category']}"), types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")]]
        
        # Send to Admin
        await bot.send_message(ADMIN_ID, f"🔔 **New Proof!**\nUser: {message.from_user.id}\nBuy: {data.get('cat_name', 'Unknown')}", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
        
        await message.answer("✅ Proof Sent! Wait for approval.")
        await state.clear()

    @dp.callback_query(F.data.startswith("approve_"))
    async def admin_approve(callback: types.CallbackQuery):
        parts = callback.data.split("_")
        settings = await get_settings()
        cat = settings["categories"].get(parts[2])
        
        # Send link to user
        try:
            await bot.send_message(int(parts[1]), f"✅ **Approved!**\nJoin: {cat['link']}")
            await callback.message.delete()
            await callback.answer("User approved.")
        except Exception as e:
            await callback.answer(f"Failed to msg user: {e}")

    @dp.callback_query(F.data.startswith("reject_"))
    async def admin_reject(callback: types.CallbackQuery):
        try:
            await bot.send_message(int(callback.data.split("_")[1]), "❌ Payment Rejected.")
            await callback.message.delete()
        except:
            pass

# ==========================================
# MAIN ENTRY
# ==========================================
async def main():
    await start_web_server()
    
    if bot and dp:
        print("♻️ Clearing previous bot sessions...")
        await bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(1)
        
        print("🚀 Bot is starting polling...")
        await dp.start_polling(bot, handle_signals=False)
    else:
        print("❌ Bot not started due to missing config.")
        # Keep process alive for Render
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
