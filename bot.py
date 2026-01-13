import logging
import io
import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode

# ==========================================
# CONFIGURATION
# ==========================================
# On Render/Heroku, set these keys in the 'Environment Variables' section
TOKEN = os.getenv("8084906584:AAHqby3b7gSfHjFw3FXqiOFUhpRAUCrabk4") 
MONGO_URL = os.getenv("mongodb+srv://paybox:Noha9980@cluster0.xngngqj.mongodb.net/?appName=Cluster0")
ADMIN_ID = 8072674531  # Your Telegram ID (Keep as int)

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
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

class AdminState(StatesGroup):
    waiting_for_upi = State()
    waiting_for_paypal = State()
    waiting_for_price = State()
    waiting_for_link = State()

class UserState(StatesGroup):
    waiting_for_proof = State()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
async def get_settings():
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "nohashekdendsouza@oksbi",
            "paypal_link": "paypal.me/example",
            "price": "100 INR",
            "vip_link": "https://t.me/+pDemZzNHnsU5MTg1"
        }
        await settings_col.insert_one(settings)
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
        [types.KeyboardButton(text="💎 Buy VIP Membership")],
        [types.KeyboardButton(text="🆘 Support")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    await message.answer(
        f"Hello {message.from_user.first_name}!\nWelcome to the Premium Bot.",
        reply_markup=keyboard
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def buy_vip_menu(message: types.Message):
    settings = await get_settings()
    price = settings.get('price')
    
    kb = [
        [types.InlineKeyboardButton(text="🇮🇳 Pay via UPI", callback_data="pay_upi")],
        [types.InlineKeyboardButton(text="🌍 Pay via PayPal", callback_data="pay_paypal")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await message.answer(
        f"💎 **VIP ACCESS**\n\nPrice: `{price}`\n\nChoose your payment method:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "pay_upi")
async def process_upi_pay(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()
    upi_id = settings.get('upi_id')
    qr_bio = generate_upi_qr(upi_id)
    
    # Use BufferedInputFile correctly
    input_file = types.BufferedInputFile(qr_bio.getvalue(), filename="qr.png")
    
    await callback.message.answer_photo(
        photo=input_file,
        caption=f"Scan to pay: `{upi_id}`\n\n⚠️ After paying, send a Screenshot here.",
        parse_mode="Markdown"
    )
    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.message(UserState.waiting_for_proof)
async def handle_proof(message: types.Message, state: FSMContext):
    user_info = f"User: {message.from_user.full_name} (ID: {message.from_user.id})"
    
    kb = [[
        types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{message.from_user.id}"),
        types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
    ]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)

    await bot.send_message(ADMIN_ID, f"🔔 **New Payment Proof!**\n{user_info}", parse_mode="Markdown")
    
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption="Proof attached.", reply_markup=keyboard)
    else:
        await bot.send_message(ADMIN_ID, f"Text Proof: {message.text}", reply_markup=keyboard)
        
    await message.answer("✅ Proof Sent! Please wait for admin approval.")
    await state.clear()

# ==========================================
# ADMIN APPROVAL
# ==========================================

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    settings = await get_settings()
    vip_link = settings.get('vip_link')
    
    try:
        await bot.send_message(user_id, f"✅ **Payment Approved!**\n\nJoin here: {vip_link}")
        await callback.message.edit_reply_markup(reply_markup=None) # Remove buttons
        await callback.answer("User Approved!")
    except Exception as e:
        await callback.answer(f"Error: {e}")

# ==========================================
# MAIN ENTRY
# ==========================================
async def main():
    print("Bot is starting...")
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())  # <--- This needs to be indented
    
