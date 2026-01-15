import os
import io
import datetime
import threading
import http.server
import socketserver
import segno
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
MONGO_URI = os.environ.get("MONGO_URI") # Add this to Render!
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
PAYPAL_LINK = os.environ.get("PAYPAL_LINK", "https://paypal.me/yourname")
BANK_DETAILS = os.environ.get("BANK_DETAILS", "Bank: XYZ\nAcc: 123456789\nIFSC: BANK0001")
CHANNEL_LINK = "https://t.me/MyAnimeEnglish"
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/YourUsername")

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URI)
db = client['payment_bot']
users_col = db['users'] # Stores all users

# --- HEALTH CHECK SERVER ---
def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    with socketserver.TCPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

# --- ADMIN DECORATOR ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Access Denied.")
            return
        return await func(update, context)
    return wrapper

# --- USER FUNCTIONS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Save/Update user in MongoDB
    if not users_col.find_one({"user_id": user.id}):
        users_col.insert_one({
            "user_id": user.id,
            "full_name": user.full_name,
            "username": f"@{user.username}" if user.username else "N/A",
            "is_vip": False,
            "join_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "expiry_date": "N/A",
            "is_banned": False
        })

    db_user = users_col.find_one({"user_id": user.id})
    if db_user.get("is_banned"):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    if 'is_auth' not in context.user_data:
        context.user_data['is_auth'] = False

    if not context.user_data['is_auth'] and user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nEnter passcode:", parse_mode="HTML")
        return

    keyboard = [[InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
                [InlineKeyboardButton("📞 Contact Support", url=SUPPORT_URL)]]
    await update.message.reply_photo(photo=WELCOME_IMAGE, caption="Welcome! Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard))

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('is_auth'): return 
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start")
    else:
        await update.message.reply_text("❌ Incorrect passcode.")

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("Monthly - ₹500", callback_data='plan_500_30')],
                [InlineKeyboardButton("Yearly - ₹5000", callback_data='plan_5000_365')]]
    await query.edit_message_caption(caption="<b>Select a Plan:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, amount, days = query.data.split("_")
    await query.answer()
    keyboard = [[InlineKeyboardButton("UPI (QR)", callback_data=f'meth_upi_{amount}_{days}')],
                [InlineKeyboardButton("PayPal", callback_data=f'meth_pay_{amount}_{days}')]]
    await query.edit_message_caption(caption=f"Selected: ₹{amount}\nChoose Method:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, method, amount, days = query.data.split("_")
    await query.answer()
    if method == "upi":
        upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
        qr = segno.make(upi_uri)
        out = io.BytesIO()
        qr.save(out, kind='png', scale=10)
        out.seek(0)
        await query.message.reply_photo(photo=out, caption=f"✅ Pay ₹{amount}\nSend screenshot with /days {days}")

# --- ADMIN FUNCTIONS ---

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gives complete details of VIP and Non-VIP users."""
    all_users = list(users_col.find())
    report = "📊 <b>Detailed User Report</b>\n\n"
    
    for u in all_users:
        status = "✨ VIP" if u['is_vip'] else "👤 User"
        report += (f"<b>{status}</b>: {u['full_name']}\n"
                   f"├ ID: <code>{u['user_id']}</code>\n"
                   f"├ User: {u['username']}\n"
                   f"├ Joined: {u['join_date']}\n"
                   f"└ Expiry: {u['expiry_date']}\n\n")
    
    # Split message if too long for Telegram
    if len(report) > 4096:
        for i in range(0, len(report), 4096):
            await update.message.reply_text(report[i:i+4096], parse_mode="HTML")
    else:
        await update.message.reply_text(report, parse_mode="HTML")

@admin_only
async def set_new_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        global BOT_PASSCODE
        BOT_PASSCODE = context.args[0]
        await update.message.reply_text(f"✅ Passcode updated: {BOT_PASSCODE}")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        caption = update.message.caption if update.message.caption else ""
        days = "30" if "365" not in caption else "365"
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 Proof from {update.effective_user.id}\nPlan: {days} Days",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"apprv_{update.effective_user.id}_{days}")]])
        )
        await update.message.reply_text("✅ Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id, days = query.data.split("_")
    expiry = (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")
    
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"is_vip": True, "expiry_date": expiry}})
    
    await context.bot.send_message(chat_id=int(user_id), text=f"🎉 Approved! Exp: {expiry}\nJoin: {CHANNEL_LINK}")
    await query.edit_message_caption(caption=f"✅ Approved until {expiry}")

# --- MAIN BLOCK ---
def main():
    threading.Thread(target=run_health_check, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("setpass", set_new_passcode))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(select_payment_method, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^meth_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^apprv_'))
    
    application.run_polling()

if __name__ == '__main__':
    main()
        
