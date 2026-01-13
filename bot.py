import logging
import io
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode
from PIL import Image

# ==========================================
# CONFIGURATION (Set these in Render Env Vars)
# ==========================================
import os
TOKEN = os.getenv("8084906584:AAHqby3b7gSfHjFw3FXqiOFUhpRAUCrabk4")
MONGO_URL = os.getenv("mongodb+srv://paybox:Noha9980@cluster0.xngngqj.mongodb.net/?appName=Cluster0")
ADMIN_ID = 8072674531 # Your Telegram ID

# ==========================================
# DATABASE SETUP (Async MongoDB)
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
# STATES FOR CONVERSATION
# ==========================================
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
        # Default settings
        settings = {
            "_id": "main_settings",
            "upi_id": "nohasheldendsouza@oksbi",
            "paypal_link": "paypal.me/example",
            "price": "100 INR",
            "vip_link": "https://t.me/+pDemZzNHnsU5MTg1"
        }
        await settings_col.insert_one(settings)
    return settings

def generate_upi_qr(upi_id, amount=None):
    # Construct UPI URI
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP_Payment&cu=INR"
    if amount:
        upi_url += f"&am={amount}"
    
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
        f"Hello {message.from_user.first_name}! \nWelcome to the Premium Bot.\n"
        "Tap 'Buy VIP Membership' to get instant access.", 
        reply_markup=keyboard
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def buy_vip_menu(message: types.Message):
    settings = await get_settings()
    price = settings.get('price')
    
    kb = [
        [types.InlineKeyboardButton(text="🇮🇳 Pay via UPI (GPay/PhonePe)", callback_data="pay_upi")],
        [types.InlineKeyboardButton(text="🌍 Pay via PayPal", callback_data="pay_paypal")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await message.answer(
        f"💎 VIP ACCESS\n\nPrice: {price}\n\nChoose your payment method below:", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "pay_upi")
async def process_upi_pay(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()
    upi_id = settings.get('upi_id')
    
    # Generate QR Code
    qr_bio = generate_upi_qr(upi_id)
    
    await callback.message.answer_photo(
        photo=types.BufferedInputFile(qr_bio.read(), filename="qr.png"),
        caption=f"Scan this QR code or pay to: {upi_id}\n\n"
                "⚠️ After paying, send a Screenshot or Transaction ID here.",
        parse_mode="Markdown"
    )
    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.callback_query(F.data == "pay_paypal")
async def process_paypal_pay(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()
    link = settings.get('paypal_link')
    
    await callback.message.answer(
        f"Click the link below to pay:\n{link}\n\n"
        "⚠️ After paying, send a Screenshot or Transaction ID here."
    )
    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.message(UserState.waiting_for_proof)
async def handle_proof(message: types.Message, state: FSMContext):
    # Forward proof to admin
    user_info = f"User: {message.from_user.full_name} (ID: {message.from_user.id})"
    
    kb = [[
        types.InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{message.from_user.id}"),
        types.InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
    ]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)

    await bot.send_message(ADMIN_ID, f"🔔 New Payment Proof!\n{user_info}", parse_mode="Markdown")
    
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption="Proof attached above.", reply_markup=keyboard)
    else:
        await bot.send_message(ADMIN_ID, f"Proof: {message.text}", reply_markup=keyboard)
        
    await message.answer("✅ Proof Sent! Please wait for admin approval. You will receive the link automatically.")
    await state.clear()

# ==========================================
# ADMIN HANDLERS (Approve/Reject)
# ==========================================

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    settings = await get_settings()
    vip_link = settings.get('vip_link')
    
    try:
        await bot.send_message(
            user_id, 
            f"✅ Payment Approved!\n\nHere is your VIP Link:\n{vip_link}\n\n(This link is single-use or private, do not share!)"
        )
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ APPROVED")
    except Exception as e:
        await callback.answer(f"Error sending link: {e}")

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    try:
        await bot.send_message(user_id, "❌ Payment Rejected. Please contact admin if this is a mistake.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ REJECTED")
    except:
        pass

# ==========================================
# ADMIN CONFIG COMMANDS
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    kb = [
        [types.InlineKeyboardButton(text="Set UPI ID", callback_data="set_upi")],
        [types.InlineKeyboardButton(text="Set PayPal", callback_data="set_paypal")],
        [types.InlineKeyboardButton(text="Set Price", callback_data="set_price")],
        [types.InlineKeyboardButton(text="Set VIP Link", callback_data="set_link")],
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("⚙️ Admin Configuration Panel", reply_markup=keyboard)

@dp.callback_query(F.data == "set_upi")
async def set_upi_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send the new UPI ID (e.g., name@okaxis):")
    await state.set_state(AdminState.waiting_for_upi)

@dp.message(AdminState.waiting_for_upi)
async def set_upi_finish(message: types.Message, state: FSMContext):
    await settings_col.update_one({"_id": "main_settings"}, {"$set": {"upi_id": message.text}})
    await message.answer("✅ UPI ID updated!")
    await state.clear()

@dp.callback_query(F.data == "set_link")
async def set_link_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send the new VIP Channel/Group Link:")
    await state.set_state(AdminState.waiting_for_link)

@dp.message(AdminState.waiting_for_link)
async def set_link_finish(message: types.Message, state: FSMContext):
    await settings_col.update_one({"_id": "main_settings"}, {"$set": {"vip_link": message.text}})
    await message.answer("✅ VIP Link updated!")
    await state.clear()

# ==========================================
# ENTRY POINT
# ==========================================
async def main():
    print("Bot is starting...")
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())
