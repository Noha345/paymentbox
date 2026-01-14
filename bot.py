iimport logging
import asyncio
import os
import sys
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
# We use .get() to avoid crashing if keys are missing locally
TOKEN = os.getenv("BOT_TOKEN", "8084906584:AAHTn6qNxYIo46ZXQOonpS4YOBIPU7GThWg") 
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://paybox:Noha9980@cluster0.xngngqj.mongodb.net/?appName=Cluster0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8072674531")) 
PORT = int(os.getenv("PORT", 8080))
# ==========================================
# DATABASE SETUP
# ==========================================
if not TOKEN or not MONGO_URL:
    print("⚠️ CRITICAL ERROR: BOT_TOKEN or MONGO_URL is missing.")
    # We don't exit here so Render doesn't crash-loop immediately, 
    # but the bot won't work without keys.
    
cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["VipBotDB"]
settings_col = db["settings"]
users_col = db["users"]

# ==========================================
# BOT SETUP
# ==========================================
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# ==========================================
# CATEGORIES & LOGIC
# ==========================================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/+pDemZzNHnsU5MTg1"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/+ExampleMovie"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/+ExampleCode"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/+ExampleGame"}
}

class UserState(StatesGroup):
    selecting_category = State()
    waiting_for_proof = State()

async def get_settings():
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "your-upi@oksbi",
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
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await users_col.update_one({"user_id": message.from_user.id}, {"$set": {"username": message.from_user.username}}, upsert=True)
    kb = [[types.KeyboardButton(text="💎 Buy VIP Membership"), types.KeyboardButton(text="🆘 Support")]]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(f"👋 **Hello {message.from_user.first_name}!**\n\nWelcome to the Premium Bot.", parse_mode="Markdown", reply_markup=keyboard)

@dp.message(F.text == "💎 Buy VIP Membership")
async def show_categories(message: types.Message):
    settings = await get_settings()
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
    kb = [[types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{data['selected_category']}"), types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")]]
    await bot.send_message(ADMIN_ID, f"🔔 **New Proof!**\nUser: {message.from_user.id}\nBuy: {data['cat_name']}", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
    await message.answer("✅ Proof Sent! Wait for approval.")
    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    settings = await get_settings()
    cat = settings["categories"].get(parts[2])
    await bot.send_message(int(parts[1]), f"✅ **Approved!**\nJoin: {cat['link']}")
    await callback.message.delete()

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(callback: types.CallbackQuery):
    await bot.send_message(int(callback.data.split("_")[1]), "❌ Payment Rejected.")
    await callback.message.delete()

# ==========================================
# MAIN ENTRY
# ==========================================
async def main():
    # 1. Start Web Server first to satisfy Render Health Check
    await start_web_server()
    
    # 2. Clear any stuck sessions (Fix for Conflict Error)
    print("♻️ Clearing previous bot sessions...")
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2) # Wait a moment for Telegram to register the logout
    
    # 3. Start Polling
    print("🚀 Bot is starting polling...")
    await dp.start_polling(bot, handle_signals=False) 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
