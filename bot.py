import logging
import asyncio
import io
import os
import datetime

# Third-party imports
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
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
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "1234")  # Default password

logging.basicConfig(level=logging.INFO)

# ==========================================
# DATABASE SETUP
# ==========================================
settings_col = None
users_col = None
purchases_col = None

async def init_db():
    global settings_col, users_col, purchases_col
    if MONGO_URL:
        try:
            cluster = AsyncIOMotorClient(MONGO_URL)
            db = cluster["VipBotDB"]
            settings_col = db["settings"]
            users_col = db["users"]
            purchases_col = db["purchases"]
            logging.info("✅ MongoDB Connected")
        except Exception as e:
            logging.error(f"❌ MongoDB Connection Failed: {e}")

# ==========================================
# BOT SETUP
# ==========================================
if TOKEN:
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
else:
    bot = None
    dp = None

# ==========================================
# DATA & STATES
# ==========================================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/example"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/example"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/example"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/example"}
}

class UserState(StatesGroup):
    awaiting_password = State()
    waiting_for_proof = State()
    broadcast_msg = State()

# ==========================================
# HELPERS
# ==========================================
async def get_settings():
    if settings_col is None:
        return None
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "nohasheldendsouza@oksbi",
            "paypal_link": "https://paypal.me/yourid",
            "bank_details": "Bank: SBI\nAcc: 123456789\nIFSC: SBIN0001234",
            "categories": DEFAULT_CATEGORIES
        }
        await settings_col.insert_one(settings)
    return settings

def generate_upi_qr(upi_id: str):
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP_Subscription&cu=INR"
    qr = qrcode.make(upi_url)
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

async def is_user_verified(user_id: int):
    if not users_col: return False
    user = await users_col.find_one({"user_id": user_id})
    return user and user.get("verified", False)

# ==========================================
# WEB SERVER
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"🌐 Web server running on port {PORT}")

# ==========================================
# ADMIN COMMANDS (NEW)
# ==========================================
if dp:
    @dp.message(Command("users"))
    async def stats_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID: return
        
        if users_col:
            total_users = await users_col.count_documents({})
            total_sales = await purchases_col.count_documents({})
            await message.answer(f"📊 **Bot Statistics**\n\n👥 Total Users: {total_users}\n🛒 Total Sales: {total_sales}")
        else:
            await message.answer("⚠️ Database not connected.")

    @dp.message(Command("broadcast"))
    async def broadcast_cmd(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📢 Please send the message you want to broadcast (Text, Photo, or Video).")
        await state.set_state(UserState.broadcast_msg)

    @dp.message(UserState.broadcast_msg)
    async def process_broadcast(message: types.Message, state: FSMContext):
        if not users_col: return
        
        await message.answer("🚀 Broadcasting started...")
        users = users_col.find({})
        count = 0
        async for user in users:
            try:
                await message.copy_to(chat_id=user['user_id'])
                count += 1
                await asyncio.sleep(0.05) # Prevent flood wait
            except Exception:
                pass
        
        await message.answer(f"✅ Broadcast complete.\nSent to {count} users.")
        await state.clear()

    @dp.message(Command("addvip"))
    async def manual_add_vip(message: types.Message):
        if message.from_user.id != ADMIN_ID: return
        
        try:
            # Usage: /addvip 123456789
            args = message.text.split()
            if len(args) < 2:
                return await message.answer("⚠️ Usage: `/addvip USER_ID`")
            
            target_id = int(args[1])
            if users_col:
                await users_col.update_one(
                    {"user_id": target_id},
                    {"$set": {"verified": True, "manual_add": True}},
                    upsert=True
                )
                await bot.send_message(target_id, "🎉 **Congratulations!**\nYou have been given VIP access by Admin.")
                await message.answer(f"✅ User {target_id} added to VIP.")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    @dp.message(Command("support"))
    async def support_cmd(message: types.Message):
        # Change this to your username
        await message.answer("🆘 **Support**\n\nContact Admin: @YourTelegramUsername")

# ==========================================
# STANDARD HANDLERS
# ==========================================
if dp:
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message, state: FSMContext):
        if users_col is None: return await message.answer("⚠️ DB Error.")

        if await is_user_verified(message.from_user.id):
            await show_main_menu(message)
        else:
            await message.answer("🔒 **Password Protected**\nEnter password:")
            await state.set_state(UserState.awaiting_password)

    @dp.message(UserState.awaiting_password)
    async def process_password(message: types.Message, state: FSMContext):
        if message.text == BOT_PASSWORD:
            if users_col:
                await users_col.update_one(
                    {"user_id": message.from_user.id},
                    {"$set": {"verified": True, "username": message.from_user.username}},
                    upsert=True
                )
            await message.answer("✅ Password Correct!")
            await state.clear()
            await show_main_menu(message)
        else:
            await message.answer("❌ Incorrect Password.")

    async def show_main_menu(message: types.Message):
        kb = [
            [types.KeyboardButton(text="💎 Buy VIP Membership")],
            [types.KeyboardButton(text="🆘 Support")]
        ]
        await message.answer("👋 Welcome to VIP Store.", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

    @dp.message(F.text == "🆘 Support")
    async def support_btn(message: types.Message):
        await support_cmd(message)

    @dp.message(F.text == "💎 Buy VIP Membership")
    async def show_categories(message: types.Message):
        if not await is_user_verified(message.from_user.id):
            return await message.answer("🔒 Login first.")
        
        settings = await get_settings()
        if not settings: return await message.answer("⚠️ Error loading settings.")

        builder = InlineKeyboardBuilder()
        for key, data in settings["categories"].items():
            builder.button(text=f"{data['name']} ({data['price']})", callback_data=f"cat_{key}")
        builder.adjust(1)
        await message.answer("✨ Select Category:", reply_markup=builder.as_markup())

    @dp.callback_query(F.data.startswith("cat_"))
    async def select_category(callback: types.CallbackQuery, state: FSMContext):
        key = callback.data.split("_")[1]
        settings = await get_settings()
        category = settings["categories"].get(key)
        
        if not category: return await callback.answer("Invalid.")
        await state.update_data(category_key=key, category_name=category['name'], price=category['price'])

        buttons = [
            [types.InlineKeyboardButton(text="🇮🇳 UPI", callback_data="pay_upi")],
            [types.InlineKeyboardButton(text="🌍 PayPal", callback_data="pay_paypal")],
            [types.InlineKeyboardButton(text="🏦 Bank", callback_data="pay_bank")]
        ]
        await callback.message.edit_text(f"💎 **{category['name']}**\n💰 {category['price']}\n\nSelect Payment:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

    @dp.callback_query(F.data.in_({"pay_upi", "pay_paypal", "pay_bank"}))
    async def show_payment(callback: types.CallbackQuery, state: FSMContext):
        settings = await get_settings()
        method = callback.data
        
        text = ""
        photo = None

        if method == "pay_upi":
            qr = generate_upi_qr(settings["upi_id"])
            photo = types.BufferedInputFile(qr.getvalue(), "upi.png")
            text = f"**Pay via UPI**\nID: `{settings['upi_id']}`\nScan & send proof."
        elif method == "pay_paypal":
            text = f"**Pay via PayPal**\nLink: {settings['paypal_link']}\nSend proof."
        elif method == "pay_bank":
            text = f"**Pay via Bank**\n{settings['bank_details']}\nSend proof."

        if photo:
            await callback.message.answer_photo(photo, caption=text, parse_mode="Markdown")
        else:
            await callback.message.answer(text, parse_mode="Markdown")
        
        await state.set_state(UserState.waiting_for_proof)
        await callback.answer()

    @dp.message(UserState.waiting_for_proof)
    async def receive_proof(message: types.Message, state: FSMContext):
        if not message.photo and not message.document:
            return await message.answer("⚠️ Send screenshot.")
        
        data = await state.get_data()
        await state.clear()
        await message.answer("✅ Proof sent to admin.")

        if ADMIN_ID:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{data.get('category_key')}")
            kb.button(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
            
            caption = f"🧾 **Proof**\nUser: {message.from_user.id}\nPlan: {data.get('category_name')}"
            
            if message.photo:
                await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb.as_markup(), parse_mode="Markdown")
            else:
                await bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=kb.as_markup(), parse_mode="Markdown")

    @dp.callback_query(F.data.startswith("approve_"))
    async def approve_user(callback: types.CallbackQuery):
        _, user_id, cat_key = callback.data.split("_")
        user_id = int(user_id)
        settings = await get_settings()
        cat = settings["categories"].get(cat_key)
        
        try:
            await bot.send_message(user_id, f"✅ **Approved!**\nLink: {cat['link']}")
            if purchases_col:
                await purchases_col.insert_one({"user_id": user_id, "item": cat['name'], "date": datetime.datetime.utcnow()})
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ APPROVED")
        except Exception as e:
            await callback.answer(f"Error: {e}")

    @dp.callback_query(F.data.startswith("reject_"))
    async def reject_user(callback: types.CallbackQuery):
        user_id = int(callback.data.split("_")[1])
        try:
            await bot.send_message(user_id, "❌ Payment Rejected.")
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ REJECTED")
        except: pass

# ==========================================
# MAIN
# ==========================================
async def main():
    await init_db()
    await start_web_server()
    if bot:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("🚀 Bot started")
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
        
