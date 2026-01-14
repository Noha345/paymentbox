import logging
import asyncio
import io
import os
import datetime

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
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "1234")  # Default password is '1234' if not set

logging.basicConfig(level=logging.INFO)

# ==========================================
# DATABASE SETUP
# ==========================================
settings_col = None
users_col = None
purchases_col = None

if not TOKEN or not MONGO_URL:
    print("⚠️ CRITICAL ERROR: BOT_TOKEN or MONGO_URL missing")

if MONGO_URL:
    try:
        cluster = AsyncIOMotorClient(MONGO_URL)
        db = cluster["VipBotDB"]
        settings_col = db["settings"]
        users_col = db["users"]
        purchases_col = db["purchases"]  # New collection for purchase history
        print("✅ MongoDB Connected")
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")
else:
    print("❌ MongoDB URL not found.")

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
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/MyAnimeEnglish"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/example"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/example"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/example"}
}

class UserState(StatesGroup):
    awaiting_password = State()
    waiting_for_proof = State()

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
    """Check if user has entered the correct password previously"""
    if not users_col:
        return False
    user = await users_col.find_one({"user_id": user_id})
    return user and user.get("verified", False)

# ==========================================
# WEB SERVER (Render)
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
    print(f"🌐 Web server running on port {PORT}")

# ==========================================
# HANDLERS
# ==========================================
if dp:

    # --- 1. START & PASSWORD LOGIC ---
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message, state: FSMContext):
        # Check database connection
        if users_col is None:
            return await message.answer("⚠️ System Error: Database not connected.")

        # Check if user is already verified
        if await is_user_verified(message.from_user.id):
            await show_main_menu(message)
        else:
            await message.answer("🔒 **This bot is password protected.**\n\nPlease enter the password to access:")
            await state.set_state(UserState.awaiting_password)

    @dp.message(UserState.awaiting_password)
    async def process_password(message: types.Message, state: FSMContext):
        if message.text == BOT_PASSWORD:
            # Save user as verified in DB
            if users_col is not None:
                await users_col.update_one(
                    {"user_id": message.from_user.id},
                    {"$set": {
                        "username": message.from_user.username,
                        "verified": True,
                        "joined_at": datetime.datetime.utcnow()
                    }},
                    upsert=True
                )
            await message.answer("✅ **Password Accepted!** You have been unlocked.")
            await state.clear()
            await show_main_menu(message)
        else:
            await message.answer("❌ **Incorrect Password.** Try again:")

    async def show_main_menu(message: types.Message):
        kb = [
            [types.KeyboardButton(text="💎 Buy VIP Membership")],
            [types.KeyboardButton(text="🆘 Support")]
        ]
        await message.answer(
            f"👋 Hello {message.from_user.first_name}!\n\nWelcome to the Premium VIP Store.",
            reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        )

    # --- 2. CATEGORY SELECTION ---
    @dp.message(F.text == "💎 Buy VIP Membership")
    async def show_categories(message: types.Message):
        # Double check verification
        if not await is_user_verified(message.from_user.id):
            return await message.answer("🔒 Please enter password first.")

        settings = await get_settings()
        if not settings:
            return await message.answer("⚠️ Database error.")

        builder = InlineKeyboardBuilder()
        for key, data in settings["categories"].items():
            builder.button(
                text=f"{data['name']} ({data['price']})",
                callback_data=f"cat_{key}"
            )
        builder.adjust(1)

        await message.answer("✨ Select a VIP Category:", reply_markup=builder.as_markup())

    # --- 3. PAYMENT METHOD SELECTION ---
    @dp.callback_query(F.data.startswith("cat_"))
    async def select_category(callback: types.CallbackQuery, state: FSMContext):
        key = callback.data.split("_")[1]
        settings = await get_settings()
        category = settings["categories"].get(key)

        if not category:
            return await callback.answer("Invalid category", show_alert=True)

        # Save selected category to state
        await state.update_data(category_key=key, category_name=category['name'], price=category['price'])

        # Show Payment Options (UPI / PayPal / Bank)
        buttons = [
            [types.InlineKeyboardButton(text="🇮🇳 UPI (QR Code)", callback_data="pay_upi")],
            [types.InlineKeyboardButton(text="🌍 PayPal", callback_data="pay_paypal")],
            [types.InlineKeyboardButton(text="🏦 Bank Transfer", callback_data="pay_bank")]
        ]
        
        await callback.message.edit_text(
            f"💎 **Selected:** {category['name']}\n💰 **Price:** {category['price']}\n\nSelect Payment Method:",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="Markdown"
        )

    # --- 4. SHOW PAYMENT DETAILS ---
    @dp.callback_query(F.data.in_({"pay_upi", "pay_paypal", "pay_bank"}))
    async def show_payment_details(callback: types.CallbackQuery, state: FSMContext):
        method = callback.data
        settings = await get_settings()
        
        if method == "pay_upi":
            qr = generate_upi_qr(settings["upi_id"])
            await callback.message.answer_photo(
                types.BufferedInputFile(qr.getvalue(), "upi.png"),
                caption=f"**Pay via UPI**\nID: `{settings['upi_id']}`\n\nScan QR to pay. Then send screenshot.",
                parse_mode="Markdown"
            )
        
        elif method == "pay_paypal":
            link = settings.get("paypal_link", "Not Available")
            await callback.message.answer(
                f"**Pay via PayPal**\n\nLink: {link}\n\nClick link to pay. Then send screenshot.",
                parse_mode="Markdown"
            )
            
        elif method == "pay_bank":
            details = settings.get("bank_details", "Not Available")
            await callback.message.answer(
                f"**Pay via Bank Transfer**\n\n{details}\n\nTransfer amount. Then send screenshot.",
                parse_mode="Markdown"
            )

        await state.set_state(UserState.waiting_for_proof)
        await callback.answer()

    # --- 5. HANDLE PROOF & ADMIN NOTIFICATION ---
    @dp.message(UserState.waiting_for_proof)
    async def receive_proof(message: types.Message, state: FSMContext):
        if not message.photo and not message.document:
            return await message.answer("⚠️ Please send an image or screenshot.")

        data = await state.get_data()
        category_name = data.get("category_name", "Unknown")
        price = data.get("price", "Unknown")
        cat_key = data.get("category_key")

        await state.clear()
        await message.answer("✅ Proof sent! Waiting for admin approval.")

        # Notify Admin
        if ADMIN_ID:
            # Create Approve/Reject buttons
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Approve", callback_data=f"approve_{message.from_user.id}_{cat_key}")
            kb.button(text="❌ Reject", callback_data=f"reject_{message.from_user.id}")
            kb.adjust(2)

            caption = (
                f"🧾 **New Payment Proof**\n"
                f"👤 User: {message.from_user.full_name} (ID: `{message.from_user.id}`)\n"
                f"📦 Plan: {category_name}\n"
                f"💰 Price: {price}"
            )
            
            # Forward the proof (photo) to admin
            if message.photo:
                await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb.as_markup(), parse_mode="Markdown")
            else:
                await bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=kb.as_markup(), parse_mode="Markdown")

    # --- 6. ADMIN APPROVE/REJECT HANDLERS ---
    @dp.callback_query(F.data.startswith("approve_"))
    async def admin_approve(callback: types.CallbackQuery):
        # Parse data: approve_USERID_CATKEY
        _, user_id, cat_key = callback.data.split("_")
        user_id = int(user_id)
        
        settings = await get_settings()
        category = settings["categories"].get(cat_key)
        
        # 1. Notify User & Send Link
        try:
            link = category['link'] if category else "Contact Admin"
            await bot.send_message(
                user_id, 
                f"✅ **Payment Approved!**\n\nHere is your link:\n{link}", 
                parse_mode="Markdown"
            )
        except Exception as e:
            await callback.answer(f"Failed to msg user: {e}", show_alert=True)
            return

        # 2. Store Purchase Data in DB
        if purchases_col is not None:
            await purchases_col.insert_one({
                "user_id": user_id,
                "category": category['name'],
                "price": category['price'],
                "approved_at": datetime.datetime.utcnow(),
                "admin_id": callback.from_user.id
            })

        await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ **APPROVED**")
        await callback.answer("Approved & Saved!")

    @dp.callback_query(F.data.startswith("reject_"))
    async def admin_reject(callback: types.CallbackQuery):
        user_id = int(callback.data.split("_")[1])
        
        try:
            await bot.send_message(user_id, "❌ Your payment proof was rejected. Please contact support.")
        except:
            pass
            
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ **REJECTED**")
        await callback.answer("Rejected")

# ==========================================
# MAIN
# ==========================================
async def main():
    await start_web_server()

    if bot and dp:
        await bot.delete_webhook(drop_pending_updates=True)
        print("🚀 Bot started polling")
        await dp.start_polling(bot)
    else:
        print("❌ Bot not started (missing env vars)")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
    
