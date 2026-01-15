import os
import io
import datetime
import threading
import http.server
import socketserver
import segno  # Ensure 'segno' is in requirements.txt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION (Set these in Render Environment Variables) ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
PAYPAL_LINK = os.environ.get("PAYPAL_LINK", "https://paypal.me/yourname")
BANK_DETAILS = os.environ.get("BANK_DETAILS", "Bank: XYZ\nAcc: 123456789\nIFSC: BANK0001")
CHANNEL_LINK = "https://t.me/MyAnimeEnglish"
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/YourUsername")

# In-memory storage (Resets when Render restarts)
registered_users = set()
vip_users = set()
banned_users = set()

# --- HEALTH CHECK SERVER ---
def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    with socketserver.TCPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

# --- ADMIN DECORATOR ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Access Denied: Admin Only.")
            return
        return await func(update, context)
    return wrapper

# --- USER FUNCTIONS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in banned_users:
        await update.message.reply_text("🚫 You are banned.")
        return
    
    if 'is_auth' not in context.user_data:
        context.user_data['is_auth'] = False

    if not context.user_data['is_auth'] and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nPlease enter the passcode to access features:", parse_mode="HTML")
        return

    registered_users.add(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
        [InlineKeyboardButton("📞 Contact Support", url=SUPPORT_URL)]
    ]
    
    try:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except:
        await update.message.reply_text("<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('is_auth'):
        return 
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start to see the menu.")
    else:
        await update.message.reply_text("❌ Incorrect passcode. Please try again:")

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Monthly - ₹500", callback_data='plan_500')],
        [InlineKeyboardButton("Yearly - ₹5000", callback_data='plan_5000')]
    ]
    await query.edit_message_caption(caption="<b>Select a Plan:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    amount = query.data.split("_")[1]
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("UPI (QR Code)", callback_data=f'meth_upi_{amount}')],
        [InlineKeyboardButton("PayPal", callback_data=f'meth_pay_{amount}')],
        [InlineKeyboardButton("Bank Transfer", callback_data=f'meth_bnk_{amount}')]
    ]
    await query.edit_message_caption(caption=f"Selected: ₹{amount}\n<b>Choose Method:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    method, amount = data[1], data[2]
    await query.answer()
    if method == "upi":
        upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
        qr = segno.make(upi_uri)
        out = io.BytesIO()
        qr.save(out, kind='png', scale=10)
        out.seek(0)
        await query.message.reply_photo(photo=out, caption=f"✅ <b>Pay ₹{amount} via UPI</b>\nScan and send screenshot.")
    elif method == "pay":
        await query.message.reply_text(f"💳 <b>PayPal:</b> {PAYPAL_LINK}")
    elif method == "bnk":
        await query.message.reply_text(f"🏦 <b>Bank Transfer:</b>\n{BANK_DETAILS}")

# --- ADMIN FUNCTIONS ---

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = len(registered_users)
    vips = len(vip_users)
    non_vips = total - vips
    text = (
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: {total}\n"
        f"✨ VIP Members: {vips}\n"
        f"👤 Non-VIP Members: {max(0, non_vips)}\n"
        f"🚫 Banned: {len(banned_users)}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
async def set_new_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setpass [new_password]")
        return
    new_code = context.args[0]
    global BOT_PASSCODE
    BOT_PASSCODE = new_code
    await update.message.reply_text(f"✅ Passcode updated to: {new_code}")

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    for user_id in registered_users:
        try: await context.bot.send_message(chat_id=user_id, text=f"📢 {msg}")
        except: continue
    await update.message.reply_text("✅ Broadcast sent.")

@admin_only
async def addvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        user_id = int(context.args[0])
        vip_users.add(user_id)
        await context.bot.send_message(chat_id=user_id, text=f"🎉 VIP Granted! Link: {CHANNEL_LINK}")
        await update.message.reply_text(f"✅ VIP Link sent to {user_id}.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 Proof from {update.effective_user.id}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"apprv_{update.effective_user.id}")]])
        )
        await update.message.reply_text("✅ Screenshot received! Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = int(query.data.split("_")[1])
    vip_users.add(user_id)
    await context.bot.send_message(chat_id=user_id, text=f"🎉 Payment Approved! Join: {CHANNEL_LINK}")
    await query.edit_message_caption(caption="✅ User Approved & Added to VIP list.")

# --- MAIN BLOCK ---

def main():
    threading.Thread(target=run_health_check, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    
    # Admin Handlers
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("setpass", set_new_passcode))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("addvip", addvip))
    
    # Callbacks & Photos
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(select_payment_method, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^meth_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^apprv_'))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.run_polling()

if __name__ == '__main__':
    main()
    
