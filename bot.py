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
MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URI)
db = client['payment_bot']
users_col = db['users']
settings_col = db['settings'] # New collection for customization

# Initialize default settings if they don't exist
if not settings_col.find_one({"id": "config"}):
    settings_col.insert_one({
        "id": "config",
        "channel_link": "https://t.me/MyAnimeEnglish",
        "monthly_price": 500,
        "yearly_price": 5000,
        "support_url": "https://t.me/YourUsername"
    })

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
    config = settings_col.find_one({"id": "config"})
    
    if not users_col.find_one({"user_id": user.id}):
        users_col.insert_one({
            "user_id": user.id,
            "full_name": user.full_name,
            "username": f"@{user.username}" if user.username else "N/A",
            "is_vip": False,
            "join_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "expiry_date": "N/A"
        })

    if 'is_auth' not in context.user_data:
        context.user_data['is_auth'] = False

    if not context.user_data['is_auth'] and user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nEnter passcode:", parse_mode="HTML")
        return

    keyboard = [[InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
                [InlineKeyboardButton("📞 Contact Support", url=config['support_url'])]]
    
    await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    config = settings_col.find_one({"id": "config"})
    
    keyboard = [
        [InlineKeyboardButton(f"Monthly - ₹{config['monthly_price']}", callback_data=f"plan_{config['monthly_price']}_30")],
        [InlineKeyboardButton(f"Yearly - ₹{config['yearly_price']}", callback_data=f"plan_{config['yearly_price']}_365")]
    ]
    await query.edit_message_caption(caption="<b>Select a Plan:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('is_auth'): return 
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start")
    else:
        await update.message.reply_text("❌ Incorrect passcode.")

# --- ADMIN CUSTOMIZATION COMMANDS ---

@admin_only
async def set_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setlink [url]")
        return
    settings_col.update_one({"id": "config"}, {"$set": {"channel_link": context.args[0]}})
    await update.message.reply_text(f"✅ VIP Link updated to: {context.args[0]}")

@admin_only
async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setprice [monthly/yearly] [amount]")
        return
    ptype, price = context.args[0].lower(), int(context.args[1])
    key = "monthly_price" if ptype == "monthly" else "yearly_price"
    settings_col.update_one({"id": "config"}, {"$set": {key: price}})
    await update.message.reply_text(f"✅ {ptype.capitalize()} price updated to ₹{price}")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_users = list(users_col.find())
    report = "📊 <b>Detailed User Report</b>\n\n"
    for u in all_users:
        status = "✨ VIP" if u.get('is_vip') else "👤 USER"
        report += (f"<b>{status}</b>: {u.get('full_name')}\n"
                   f"├ ID: <code>{u.get('user_id')}</code>\n"
                   f"├ User: {u.get('username')}\n"
                   f"├ Joined: {u.get('join_date')}\n"
                   f"└ Expiry: {u.get('expiry_date')}\n\n")
    await update.message.reply_text(report, parse_mode="HTML")

# --- PAYMENT FLOW ---

async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, amount, days = query.data.split("_")
    await query.answer()
    keyboard = [[InlineKeyboardButton("UPI (QR)", callback_data=f'meth_upi_{amount}_{days}')]]
    await query.edit_message_caption(caption=f"Selected: ₹{amount}\nChoose Method:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, amount, days = query.data.split("_")
    await query.answer()
    upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
    qr = segno.make(upi_uri)
    out = io.BytesIO()
    qr.save(out, kind='png', scale=10)
    out.seek(0)
    await query.message.reply_photo(photo=out, caption=f"✅ Pay ₹{amount}\nSend screenshot after paying.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 Proof from {update.effective_user.id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve 30 Days", callback_data=f"apprv_{update.effective_user.id}_30")],
                [InlineKeyboardButton("✅ Approve 365 Days", callback_data=f"apprv_{update.effective_user.id}_365")]
            ])
        )
        await update.message.reply_text("✅ Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id, days = query.data.split("_")
    config = settings_col.find_one({"id": "config"})
    expiry = (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")
    
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"is_vip": True, "expiry_date": expiry}})
    
    await context.bot.send_message(chat_id=int(user_id), text=f"🎉 Approved! Exp: {expiry}\nJoin: {config['channel_link']}")
    await query.edit_message_caption(caption=f"✅ Approved until {expiry}")

# --- MAIN BLOCK ---
def main():
    threading.Thread(target=run_health_check, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("setlink", set_link))
    application.add_handler(CommandHandler("setprice", set_price))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(select_payment_method, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^meth_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^apprv_'))
    
    application.run_polling()

if __name__ == '__main__':
    main()
    
