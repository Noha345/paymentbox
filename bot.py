import logging
import io
import asyncio
import os
import sys
from aiohttp import web  # Required for Render Web Service
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder 
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode

# ==========================================
# CONFIGURATION 
# ==========================================
# FIX: We use the second argument as a fallback so the bot works immediately
TOKEN = os.getenv("BOT_TOKEN", "8084906584:AAHqby3b7gSfHjFw3FXqiOFUhpRAUCrabk4") 
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://paybox:Noha9980@cluster0.xngngqj.mongodb.net/?appName=Cluster0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8072674531")) 
PORT = int(os.getenv("PORT", 8080))

# Check if keys are present (Double check)
if not TOKEN or not MONGO_URL:
    sys.exit("Error: BOT_TOKEN or MONGO_URL is missing. Please check your configuration.")

# ==========================================
# DATABASE SETUP
# ==========================================
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
# DEFINING CATEGORIES
# ==========================================
DEFAULT_CATEGORIES = {
    "adult": {
        "name": "🔞 Adult Hub",
        "price": "1 INR",
        "link": "https://t.me/+pDemZzNHnsU5MTg1"
    },
    "movie": {
        "name": "🎬 Movies & Series",
        "price": "100 INR",
        "link": "https://t.me/+ExampleMovieLink"
    },
    "coding": {
        "name": "💻 Coding Resources",
        "price": "200 INR",
        "link": "https://t.me/+ExampleCodingLink"
    },
    "gaming": {
        "name": "🎮 Gaming & Mods",
        "price": "120 INR",
        "link": "https://t.me/+ExampleGameLink"
    }
}

class UserState(StatesGroup):
    selecting_category = State()
    waiting_for_proof = State()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
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
        await settings_col.update_one(
            {"_id": "main_settings"}, 
            {"$set": {"categories": DEFAULT_CATEGORIES}}
        )
        settings["categories"] = DEFAULT_CATEGORIES
        
    return settings

def generate_upi_qr(upi_id, amount=None):
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
# RENDER WEB SERVER
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
    logging.info(f"Web server started on port {PORT}")

# ==========================================
# USER HANDLERS
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await users_col.update_one(
        {"user_id": message.from_user.id}, 
        {"$set": {"username": message.from_user.username}}, 
        upsert=True
    )
    
    kb = [
        [types.KeyboardButton(text="💎 Buy VIP Membership"), types.KeyboardButton(text="🆘 Support")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Select an option...")
    
    await message.answer(
        f"👋 **Hello {message.from_user.first_name}!**\n\nWelcome to the Premium Bot.\nTap a button below to get started.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def show_categories(message: types.Message):
    settings = await get_settings()
    cats = settings.get("categories", {})
    
    # === GRID LAYOUT FOR BUTTONS ===
    builder = InlineKeyboardBuilder()
    
    for key, data in cats.items():
        btn_text = f"{data['name']} ({data['price']})"
        builder.button(text=btn_text, callback_data=f"cat_{key}")
    
    builder.adjust(2)
    
    await message.answer(
        "✨ **VIP Access Hub** ✨\n\nSelect a category to unlock exclusive content:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_selection(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split("_")[1]
    settings = await get_settings()
    category = settings["categories"].get(cat_key)
    
    if not category:
        await callback.answer("Category not found.", show_alert=True)
        return

    await state.update_data(selected_category=cat_key, price=category['price'], cat_name=category['name'])
    
    kb = [
        [types.InlineKeyboardButton(text="🇮🇳 Pay via UPI", callback_data="pay_upi")],
        [types.InlineKeyboardButton(text="🌍 Pay via PayPal", callback_data="pay_paypal")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await callback.message.edit_text(
        f"💎 **You Selected:** {category['name']}\n"
        f"💰 **Total Price:** {category['price']}\n\n"
        "👇 **Select Payment Method:**",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "pay_upi")
async def process_upi_pay(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()
    upi_id = settings.get('upi_id')
    qr_bio = generate_upi_qr(upi_id)
    input_file = types.BufferedInputFile(qr_bio.getvalue(), filename="qr.png")
    
    data = await state.get_data()
    price = data.get("price", "Unknown")
    
    await callback.message.answer_photo(
        photo=input_file,
        caption=f"📲 **Scan to Pay**\n\nAmount: `{price}`\nUPI ID: `{upi_id}`\n\n📸 **Action Required:**\nSend a screenshot of the payment here to verify.",
        parse_mode="Markdown"
    )
    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.message(UserState.waiting_for_proof)
async def handle_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_key = data.get("selected_category")
    cat_name = data.get("cat_name")

    if not cat_key:
        await message.answer("Session expired. Please click 'Buy VIP Membership' again.")
        await state.clear()
        return

    user_info = f"👤 User: {message.from_user.full_name} (ID: `{message.from_user.id}`)"
    purchase_info = f"🎁 **Category:** {cat_name}"

    kb = [[
        types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{cat_key}"),
        types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
    ]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)

    await bot.send_message(ADMIN_ID, f"🔔 **New Payment Proof!**\n\n{user_info}\n{purchase_info}", parse_mode="Markdown")
    
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption="📄 **Proof Attached**", reply_markup=keyboard)
    else:
        await bot.send_message(ADMIN_ID, f"📄 **Text Proof:** {message.text}", reply_markup=keyboard)
        
    await message.answer("✅ **Proof Received!**\n\nPlease wait while an admin verifies your payment. You will receive the link here shortly.")
    await state.clear()

# ==========================================
# ADMIN APPROVAL
# ==========================================
@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        user_id = int(parts[1])
        cat_key = parts[2]
        
        settings = await get_settings()
        category = settings["categories"].get(cat_key)
        
        if not category:
            await callback.answer("Error: Category data missing.")
            return

        vip_link = category['link']
        cat_name = category['name']
        
        await bot.send_message(
            user_id, 
            f"🎉 **Congratulations!**\n\n"
            f"Your payment for **{cat_name}** has been approved.\n"
            f"👇 **Join here:**\n{vip_link}\n\n"
            f"_(Do not share this link)_"
        )
        
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(f"✅ Approved **{cat_name}** for user {user_id}.")
        await callback.answer("Approved!")
        
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)
        logging.error(f"Approval Error: {e}")

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    await bot.send_message(user_id, "❌ **Payment Issue**\n\nYour payment proof was rejected. Please contact support.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Rejected.")

# ==========================================
# MAIN ENTRY
# ==========================================
async def main():
    await start_web_server()
    print("Bot is starting polling...")
    await dp.start_polling(bot)
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
    
