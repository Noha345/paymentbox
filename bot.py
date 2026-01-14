import logging
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 123456789  # Replace with your Telegram ID
CHANNEL_LINK = "https://t.me/+YourPrivateLink"
CHANNEL_ID = -1001234567890 # Your VIP Channel ID
WELCOME_IMAGE = "https://your-image-url.com/welcome.jpg"
QR_CODE_IMAGE = "https://your-image-url.com/qr.jpg"

# VIP Plans Data
PLANS = {
    "monthly": {"name": "Monthly VIP", "price": "₹500", "days": 30},
    "yearly": {"name": "Yearly VIP", "price": "₹5000", "days": 365}
}

# --- LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends start message with glass buttons."""
    keyboard = [
        [InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')],
        [InlineKeyboardButton("👤 My Subscription", callback_data='my_sub'),
         InlineKeyboardButton("📞 Contact Support", url="https://t.me/YourAdminUsername")],
        [InlineKeyboardButton("🔐 Set Passcode", callback_data='set_pass')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send image with buttons
    await update.message.reply_photo(
        photo=WELCOME_IMAGE,
        caption="<b>Welcome to Paybox VIP!</b>\n\nAccess premium content and exclusive signals.",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def view_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton(f"{v['name']} - {v['price']}", callback_data=f"plan_{k}")] for k, v in PLANS.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='back_to_start')])
    
    await query.edit_message_caption(
        caption="<b>Select a VIP Plan:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    plan_key = query.data.replace("plan_", "")
    context.user_data['selected_plan'] = plan_key
    
    keyboard = [
        [InlineKeyboardButton("Google Pay", callback_data='pay_now'), InlineKeyboardButton("PhonePe", callback_data='pay_now')],
        [InlineKeyboardButton("Paytm", callback_data='pay_now'), InlineKeyboardButton("PayPal/Bank", callback_data='pay_now')]
    ]
    
    await query.edit_message_caption(
        caption=f"Selected: {PLANS[plan_key]['name']}\n\n<b>Choose Payment Method:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.reply_photo(
        photo=QR_CODE_IMAGE,
        caption="✅ <b>Scan to Pay</b>\n\nAfter payment, send a <b>SCREENSHOT</b> here to verify your VIP access.",
        parse_mode="HTML"
    )

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forwards screenshot to Admin"""
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=f"💳 <b>Payment Proof</b>\nUser: {update.effective_user.id}\nName: {update.effective_user.first_name}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{update.effective_user.id}"),
                 InlineKeyboardButton("❌ Decline", callback_data=f"decline_{update.effective_user.id}")]
            ]),
            parse_mode="HTML"
        )
        await update.message.reply_text("✅ Receipt received! Admin is verifying. You will get the link shortly.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, user_id = query.data.split("_")
    
    if action == "approve":
        # Generate receipt
        now = datetime.datetime.now()
        receipt = (
            "🎉 <b>Transaction Successful!</b>\n\n"
            f"📅 Date: {now.strftime('%d/%m/%Y')}\n"
            f"⏰ Time: {now.strftime('%H:%M')}\n"
            f"🚀 Access: {CHANNEL_LINK}"
        )
        await context.bot.send_message(chat_id=user_id, text=receipt, parse_mode="HTML")
        await query.edit_message_caption(caption="✅ User Approved.")
    else:
        await context.bot.send_message(chat_id=user_id, text="❌ Payment declined. Please contact support.")
        await query.edit_message_caption(caption="❌ User Declined.")

# --- MAIN ---
def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(view_plans, pattern='^view_plans$'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(show_qr, pattern='^pay_now$'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^(approve|decline)_'))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    # Conflict check: Ensure only one instance runs
    print("Bot is starting... Ensure no other instances are running.")
    application.run_polling()

if __name__ == '__main__':
    main()
