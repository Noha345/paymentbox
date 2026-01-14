import logging
import asyncio
import io
import os
import datetime
from typing import Optional, Dict, Any

# Third-party imports
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
class Config:
    TOKEN = os.getenv("BOT_TOKEN")
    MONGO_URL = os.getenv("MONGO_URL")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    PORT = int(os.getenv("PORT", 8080))
    BOT_PASSWORD = os.getenv("BOT_PASSWORD", "1234")
    
    # Default Categories if DB is empty
    DEFAULT_SETTINGS = {
        "_id": "main_settings",
        "upi_id": "example@oksbi",
        "paypal_link": "https://paypal.me/example",
        "bank_details": "Bank: X\nAcc: 123\nIFSC: X123",
        "categories": {
            "movie": {"name": "🎬 Movies", "price": "100 INR", "link": "https://t.me/+example"},
        }
    }

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==========================================
# 🗄️ DATABASE MANAGER
# ==========================================
class Database:
    def __init__(self, uri: str):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client["VipBotDB"]
        self.settings = self.db["settings"]
        self.users = self.db["users"]
        self.purchases = self.db["purchases"]

    async def get_settings(self) -> Dict:
        """Fetch settings or initialize defaults."""
        data = await self.settings.find_one({"_id": "main_settings"})
        if not data:
            await self.settings.insert_one(Config.DEFAULT_SETTINGS)
            return Config.DEFAULT_SETTINGS
        return data

    async def verify_user(self, user_id: int, username: str = None):
        """Mark a user as verified (password entered)."""
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"verified": True, "username": username, "joined_at": datetime.datetime.now()}},
            upsert=True
        )

    async def is_verified(self, user_id: int) -> bool:
        user = await self.users.find_one({"user_id": user_id})
        return user.get("verified", False) if user else False

    async def add_purchase(self, user_id: int, item_name: str):
        await self.purchases.insert_one({
            "user_id": user_id, 
            "item": item_name, 
            "date": datetime.datetime.now()
        })
    
    async def get_all_users(self):
        return self.users.find({})

    async def get_stats(self):
        users = await self.users.count_documents({})
        sales = await self.purchases.count_documents({})
        return users, sales

    # --- NEW METHODS ADDED ---
    async def add_category(self, key: str, name: str, price: str, link: str):
        """Add or update a store category dynamically."""
        await self.settings.update_one(
            {"_id": "main_settings"},
            {"$set": {f"categories.{key}": {"name": name, "price": price, "link": link}}},
            upsert=True
        )

    async def get_user_purchases(self, user_id: int):
        """Fetch purchase history for a specific user."""
        cursor = self.purchases.find({"user_id": user_id}).sort("date", -1)
        return await cursor.to_list(length=10)

# ==========================================
# 🤖 BOT SETUP
# ==========================================
if not Config.TOKEN or not Config.MONGO_URL:
    logging.critical("❌ BOT_TOKEN or MONGO_URL missing in .env")
    exit(1)

# Initialize DB
db = Database(Config.MONGO_URL)

# Initialize Bot with HTML parsing globally
bot = Bot(token=Config.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# 🧠 STATES & HELPERS
# ==========================================
class UserState(StatesGroup):
    awaiting_password = State()
    waiting_for_proof = State()
    broadcast_msg = State()

def generate_qr(data: str) -> io.BytesIO:
    qr = qrcode.make(data)
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ==========================================
# 🛡️ ADMIN HANDLERS
# ==========================================
@dp.message(Command("users"))
async def admin_stats(message: types.Message):
    if message.from_user.id != Config.ADMIN_ID: return
    users, sales = await db.get_stats()
    await message.answer(f"📊 <b>Bot Statistics</b>\n\n👥 Total Verified Users: {users}\n🛒 Total Sales: {sales}")

@dp.message(Command("addvip"))
async def admin_manual_add(message: types.Message):
    if message.from_user.id != Config.ADMIN_ID: return
    try:
        _, target_id = message.text.split()
        target_id = int(target_id)
        await db.verify_user(target_id)
        await bot.send_message(target_id, "🎉 <b>Congratulations!</b>\nYou have been granted VIP access by Admin.")
        await message.answer(f"✅ User <code>{target_id}</code> verified.")
    except ValueError:
        await message.answer("⚠️ Usage: <code>/addvip 123456789</code>")

@dp.message(Command("broadcast"))
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != Config.ADMIN_ID: return
    await message.answer("📢 <b>Broadcast Mode</b>\nSend the message (Text/Image/Video) you want to send to all users.")
    await state.set_state(UserState.broadcast_msg)

@dp.message(UserState.broadcast_msg)
async def admin_broadcast_process(message: types.Message, state: FSMContext):
    await message.answer("🚀 Broadcasting started... This might take a while.")
    users_cursor = await db.get_all_users()
    
    success = 0
    blocked = 0
    
    async for user in users_cursor:
        user_id = user['user_id']
        try:
            await message.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05) # Basic throttle
        except TelegramForbiddenError:
            blocked += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.copy_to(chat_id=user_id)
                success += 1
            except: pass
        except Exception as e:
            logging.error(f"Failed to send to {user_id}: {e}")

    await message.answer(f"✅ <b>Broadcast Complete</b>\n\nSent: {success}\nBlocked/Failed: {blocked}")
    await state.clear()

# --- NEW ADMIN COMMAND: ADD ITEM ---
@dp.message(Command("additem"))
async def admin_add_item(message: types.Message):
    # Security check: Only Admin can use this
    if message.from_user.id != Config.ADMIN_ID: return

    try:
        # Extract arguments after the command
        args_text = message.text.replace("/additem", "").strip()
        
        # Split by "|" separator
        parts = [p.strip() for p in args_text.split("|")]
        
        if len(parts) != 4:
            raise ValueError("Wrong number of arguments")

        key, name, price, link = parts
        
        # Update Database
        await db.add_category(key, name, price, link)
        
        await message.answer(
            f"✅ <b>Item Added Successfully!</b>\n\n"
            f"🆔 Key: <code>{key}</code>\n"
            f"📦 Name: {name}\n"
            f"💰 Price: {price}\n"
            f"🔗 Link: <a href='{link}'>Check Link</a>"
        )

    except ValueError:
        await message.answer(
            "⚠️ <b>Incorrect Format</b>\n\n"
            "Use: <code>/additem key | Name | Price | Link</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/additem netflix | Netflix 1 Month | 200 INR | https://t.me/example</code>"
        )

# ==========================================
# 🔐 AUTHENTICATION
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    is_verified = await db.is_verified(message.from_user.id)
    
    if is_verified:
        await show_main_menu(message)
    else:
        await message.answer("🔒 <b>Protected Bot</b>\nPlease enter the access password:")
        await state.set_state(UserState.awaiting_password)

@dp.message(UserState.awaiting_password)
async def process_password(message: types.Message, state: FSMContext):
    if message.text == Config.BOT_PASSWORD:
        await db.verify_user(message.from_user.id, message.from_user.username)
        await message.answer("✅ <b>Access Granted!</b>")
        await state.clear()
        await show_main_menu(message)
    else:
        await message.answer("❌ <b>Wrong Password.</b> Try again:")

async def show_main_menu(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="💎 Buy VIP Membership")
    kb.button(text="👤 My Plan")
    kb.button(text="🆘 Support")
    kb.adjust(2)
    await message.answer(
        f"👋 Welcome <b>{message.from_user.first_name}</b>!", 
        reply_markup=kb.as_markup(resize_keyboard=True)
    )

# ==========================================
# 🛍️ STORE LOGIC & USER PROFILE
# ==========================================
@dp.message(F.text == "💎 Buy VIP Membership")
async def store_categories(message: types.Message):
    if not await db.is_verified(message.from_user.id): return
    
    settings = await db.get_settings()
    builder = InlineKeyboardBuilder()
    
    for key, data in settings.get("categories", {}).items():
        builder.button(text=f"{data['name']} - {data['price']}", callback_data=f"buy_{key}")
    
    builder.adjust(1)
    await message.answer("✨ <b>Select a Plan:</b>", reply_markup=builder.as_markup())

# --- NEW USER COMMAND: MY PLAN ---
@dp.message(F.text == "👤 My Plan")
@dp.message(Command("myplan"))
async def cmd_my_plan(message: types.Message):
    # Check if user is verified
    if not await db.is_verified(message.from_user.id):
        return await message.answer("🔒 You are not logged in.")

    # Fetch purchases
    purchases = await db.get_user_purchases(message.from_user.id)
    
    if not purchases:
        return await message.answer(f"👤 <b>User:</b> {message.from_user.full_name}\n\n📂 You haven't purchased any plans yet.")

    # Format the list
    history_text = "\n".join([f"• {p['item']} ({p['date'].strftime('%Y-%m-%d')})" for p in purchases])
    
    await message.answer(
        f"👤 <b>User Profile:</b> {message.from_user.full_name}\n\n"
        f"🛍️ <b>Purchase History:</b>\n"
        f"{history_text}"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def store_payment_methods(callback: types.CallbackQuery, state: FSMContext):
    cat_key = callback.data.split("_")[1]
    settings = await db.get_settings()
    category = settings["categories"].get(cat_key)
    
    if not category: return await callback.answer("Plan not found.")
    
    # Save selection to state
    await state.update_data(cat_key=cat_key, cat_name=category['name'], price=category['price'])
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇳 UPI", callback_data="pay_upi")
    kb.button(text="🌍 PayPal", callback_data="pay_paypal")
    kb.button(text="🏦 Bank", callback_data="pay_bank")
    kb.adjust(2)
    
    await callback.message.edit_text(
        f"💎 <b>{category['name']}</b>\n💰 Price: {category['price']}\n\nSelect Payment Method:",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.in_({"pay_upi", "pay_paypal", "pay_bank"}))
async def store_show_payment_details(callback: types.CallbackQuery, state: FSMContext):
    settings = await db.get_settings()
    method = callback.data
    caption = ""
    photo_file = None
    
    if method == "pay_upi":
        upi_id = settings.get('upi_id', 'N/A')
        upi_url = f"upi://pay?pa={upi_id}&pn=VIP&cu=INR"
        qr_bytes = generate_qr(upi_url)
        photo_file = types.BufferedInputFile(qr_bytes.getvalue(), filename="qr.png")
        caption = f"<b>Pay via UPI</b>\nID: <code>{upi_id}</code>\n\nScan QR or copy ID. Send screenshot after payment."
        
    elif method == "pay_paypal":
        link = settings.get('paypal_link', '#')
        caption = f"<b>Pay via PayPal</b>\nLink: <a href='{link}'>Click Here</a>\n\nSend screenshot after payment."
        
    elif method == "pay_bank":
        details = settings.get('bank_details', 'N/A')
        caption = f"<b>Pay via Bank</b>\n<pre>{details}</pre>\n\nSend screenshot after payment."

    await state.set_state(UserState.waiting_for_proof)
    
    if photo_file:
        await callback.message.answer_photo(photo_file, caption=caption)
    else:
        await callback.message.answer(caption, disable_web_page_preview=True)
        
    await callback.answer()

# ==========================================
# 📸 PROOF & APPROVAL
# ==========================================
@dp.message(UserState.waiting_for_proof)
async def process_proof(message: types.Message, state: FSMContext):
    if not (message.photo or message.document):
        return await message.answer("⚠️ Please send the payment screenshot (Image or File).")
    
    data = await state.get_data()
    await state.clear()
    
    # Notify User
    await message.answer("✅ <b>Proof Received!</b>\nAdmin will verify shortly.")
    
    # Notify Admin
    if Config.ADMIN_ID:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Approve", callback_data=f"appr_{message.from_user.id}_{data['cat_key']}")
        kb.button(text="❌ Reject", callback_data=f"rej_{message.from_user.id}")
        
        caption = (
            f"🧾 <b>New Purchase Request</b>\n"
            f"👤 User: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
            f"📦 Plan: {data['cat_name']}\n"
            f"💰 Price: {data['price']}"
        )
        
        # Send proof to admin
        if message.photo:
            await bot.send_photo(Config.ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb.as_markup())
        else:
            await bot.send_document(Config.ADMIN_ID, message.document.file_id, caption=caption, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("appr_"))
async def admin_approve(callback: types.CallbackQuery):
    _, user_id, cat_key = callback.data.split("_")
    user_id = int(user_id)
    
    settings = await db.get_settings()
    category = settings["categories"].get(cat_key)
    
    if category:
        try:
            # 1. Send Link to User
            await bot.send_message(
                user_id, 
                f"🎉 <b>Payment Accepted!</b>\n\nHere is your link:\n{category['link']}"
            )
            # 2. Log Purchase
            await db.add_purchase(user_id, category['name'])
            # 3. Update Admin Message
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ <b>APPROVED</b>")
        except Exception as e:
            await callback.answer(f"Error: {e}")
    else:
        await callback.answer("Category no longer exists.")

@dp.callback_query(F.data.startswith("rej_"))
async def admin_reject(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    try:
        await bot.send_message(user_id, "❌ <b>Payment Rejected.</b>\nPlease contact support if this is a mistake.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ <b>REJECTED</b>")
    except:
        pass

@dp.message(F.text == "🆘 Support")
async def support_handler(message: types.Message):
    await message.answer(f"🆘 <b>Support</b>\nContact Admin: <a href='tg://user?id={Config.ADMIN_ID}'>Click Here</a>")

# ==========================================
# 🌍 WEB SERVER & MAIN
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is Alive")

async def main():
    # 1. Web Server for Health Checks
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    logging.info(f"🌐 Web Server running on port {Config.PORT}")

    # 2. Start Bot
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info(f"🚀 Bot started as @{(await bot.get_me()).username}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped")
