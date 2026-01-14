import os
import logging
import datetime
import threading
import http.server
import socketserver
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 123456789  # Replace with your actual numeric Telegram ID
CHANNEL_LINK = "https://t.me/+YourPrivateLink"
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
QR_CODE_IMAGE = "https://your-image-url.com/qr.jpg"

PLANS = {
    "monthly": {"name": "Monthly VIP", "price": "₹500", "days": 30},
    "yearly": {"name": "Yearly VIP", "price": "₹5000", "days": 365}
}

# --- HEALTH CHECK SERVER (Fixes Port Timeout) ---
def run_health_check():
    """Starts a simple server to satisfy Render's port requirement."""
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    # Bind to 0.0.0.0 so Render can detect the port
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        print(f"Health check server running on port {port}...")
        httpd.serve_forever()

# --- BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
        [InlineKeyboardButton("👤 My Subscription", callback_data='my_sub'),
         InlineKeyboardButton("📞 Contact Support", url="https://t.me/YourAdminUsername")],
        [InlineKeyboardButton("🔐 Set Passcode", callback_data='set_pass')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_photo(
        photo=WELCOME_IMAGE,
        caption="<b>Welcome to Paybox VIP!</b>\n\nAccess premium content.",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"plan_{k}")] for k, v in PLANS.items()]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='back_to_start')])
    await query.edit_message_caption(caption="<b>Select a VIP Plan:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_payment_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    plan_key = query.data.replace("plan_", "")
    context.user_data['selected_plan'] = plan_key
    keyboard = [
        [InlineKeyboardButton("Google Pay", callback_data='pay_now'), InlineKeyboardButton("PhonePe", callback_data='pay_now')],
        [InlineKeyboardButton("Paytm", callback_data='pay_now'), InlineKeyboardButton("PayPal/Bank", callback_data='pay_now')]
    ]
    await query.edit_message_caption(caption=f"Selected: {PLANS[plan_key]['name']}\n\n<b>Choose Payment Method:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_photo(photo=QR_CODE_IMAGE, caption="✅ <b>Scan to Pay</b>\n\nAfter payment, send a <b>SCREENSHOT</b> here.", parse_mode="HTML")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 <b>Payment Proof</b>\nUser ID: {update.effective_user.id}\nName: {update.effective_user.first_name}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{update.effective_user.id}"), InlineKeyboardButton("❌ Decline", callback_data=f"decline_{update.effective_user.id}")]])
        )
        await update.message.reply_text("✅ Receipt received! Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, user_id = query.data.split("_")
    if action == "approve":
        receipt = f"🎉 <b>Transaction Successful!</b>\n🚀 Access: {CHANNEL_LINK}"
        await context.bot.send_message(chat_id=user_id, text=receipt, parse_mode="HTML")
        await query.edit_message_caption(caption="✅ User Approved.")
    else:
        await context.bot.send_message(chat_id=user_id, text="❌ Payment declined.", parse_mode="HTML")
        await query.edit_message_caption(caption="❌ User Declined.")

# --- MAIN BLOCK ---

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not found!")
        return

    # Start Health Check Server in a background thread
    threading.Thread(target=run_health_check, daemon=True).start()

    # Build and Start Bot
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(handle_payment_selection, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(show_qr, pattern='^pay_now$'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^(approve|decline)_'))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
    
