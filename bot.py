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
ADMIN_UPI = os.environ.get("ADMIN_UPI", "nohasheldendsouza@oksbi")
PAYPAL_LINK = os.environ.get("PAYPAL_LINK", "https://paypal.me/yourname")
BANK_DETAILS = os.environ.get("BANK_DETAILS", "Bank: XYZ\nAcc: 123456789\nIFSC: BANK0001")
CHANNEL_LINK = "https://t.me/MyAnimeEnglish"
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"

# In-memory storage (Resets on restart - Use MongoDB for persistence)
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
    registered_users.add(update.effective_user.id)
    keyboard = [[InlineKeyboardButton("💎 View VIP Plans", callback_data='view_plans')]]
    try:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except:
        await update.message.reply_text("<b>Welcome!</b> Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

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
    context.user_data['amount'] = amount
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("UPI (QR Code)", callback_data=f'method_upi_{amount}')],
        [InlineKeyboardButton("PayPal", callback_data=f'method_paypal_{amount}')],
        [InlineKeyboardButton("Bank Transfer", callback_data=f'method_bank_{amount}')]
    ]
    await query.edit_message_caption(caption=f"Selected: ₹{amount}\n<b>Choose Payment Method:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    method = data[1]
    amount = data[2]
    await query.answer()

    if method == "upi":
        upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
        qr = segno.make(upi_uri) # Auto-generate QR
        out = io.BytesIO()
        qr.save(out, kind='png', scale=10)
        out.seek(0)
        await query.message.reply_photo(photo=out, caption=f"✅ <b>Pay ₹{amount} via UPI</b>\nScan & send Screenshot.", parse_mode="HTML")
    
    elif method == "paypal":
        await query.message.reply_text(f"💳 <b>Pay via PayPal</b>\nLink: {PAYPAL_LINK}\n\nAmount: ₹{amount}\nSend screenshot after paying.", parse_mode="HTML")
    
    elif method == "bank":
        await query.message.reply_text(f"🏦 <b>Bank Transfer</b>\n{BANK_DETAILS}\n\nSend screenshot after paying.", parse_mode="HTML")

# --- ADMIN COMMANDS ---

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    for user_id in registered_users:
        try: await context.bot.send_message(chat_id=user_id, text=f"📢 <b>BROADCAST:</b>\n{msg}", parse_mode="HTML")
        except: continue
    await update.message.reply_text("✅ Broadcast sent.")

@admin_only
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args: banned_users.add(int(context.args[0]))
    await update.message.reply_text("🚫 User Banned.")

@admin_only
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args: banned_users.discard(int(context.args[0]))
    await update.message.reply_text("✅ User Unbanned.")

@admin_only
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args: await context.bot.send_message(chat_id=int(context.args[0]), text="⚠️ <b>WARNING:</b> Terms violation.")
    await update.message.reply_text("⚠️ Warning sent.")

@admin_only
async def addvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        user_id = int(context.args[0])
        await context.bot.send_message(chat_id=user_id, text=f"🎉 VIP Access Granted!\nLink: {CHANNEL_LINK}")
        await update.message.reply_text(f"✅ VIP Link sent to {user_id}.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, 
            caption=f"💳 Proof from {update.effective_user.id}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{update.effective_user.id}")]]))
        await update.message.reply_text("✅ Screenshot received! Admin is verifying.")

# --- MAIN ---
def main():
    threading.Thread(target=run_health_check, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
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
    
