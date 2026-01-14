import os
import io
import datetime
import threading
import http.server
import socketserver
import segno  # Library for QR generation
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
ADMIN_UPI = os.environ.get("ADMIN_UPI", "your@upi")
PAYPAL_LINK = os.environ.get("PAYPAL_LINK", "https://paypal.me/yourname")
BANK_DETAILS = os.environ.get("BANK_DETAILS", "Bank: XYZ\nAcc: 123456789\nIFSC: BANK0001")
CHANNEL_LINK = "https://t.me/MyAnimeEnglish"
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")  # Set your password here
SUPPORT_URL = f"https://t.me/YourUsername" # Replace with your Telegram handle

# In-memory storage (Resets on restart)
registered_users = set()
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

# --- USER HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in banned_users:
        await update.message.reply_text("🚫 You are banned from this bot.")
        return
    
    # Initialize authentication status
    if 'is_auth' not in context.user_data:
        context.user_data['is_auth'] = False

    # Check if user needs to enter password
    if not context.user_data['is_auth'] and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nPlease enter the passcode to access features:", parse_mode="HTML")
        return

    registered_users.add(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
        [InlineKeyboardButton("📞 Contact Support", url=SUPPORT_URL)] # Support button
    ]
    
    try:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except:
        await update.message.reply_text("<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks the text input for the correct passcode."""
    if context.user_data.get('is_auth'):
        return # Ignore if already unlocked

    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start to open the menu.")
    else:
        await update.message.reply_text("❌ Incorrect passcode. Please try again:")

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not context.user_data.get('is_auth') and update.effective_user.id != ADMIN_ID:
        await query.answer("🔐 Access Denied. Unlock the bot first.", show_alert=True)
        return
        
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Monthly - ₹500", callback_data='plan_500')],
        [InlineKeyboardButton("Yearly - ₹5000", callback_data='plan_5000')]
    ]
    await query.edit_message_caption(caption="<b>Select a Plan:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# ... (Include your existing select_payment_method, handle_payment, broadcast, ban, unban, warn, addvip, and verify_payment functions here)

# --- MAIN ---
def main():
    threading.Thread(target=run_health_check, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    
    # Password checker handler (must be before other text handlers)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("addvip", addvip))
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(select_payment_method, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^method_'))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.run_polling()

if __name__ == '__main__':
    main()
