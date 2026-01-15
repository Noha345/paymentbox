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
# Automatically detects if you named it MONGO or MANGO
MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MANGO_URI")
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
WELCOME_IMAGE = os.environ.get("WELCOME_IMAGE", "https://files.catbox.moe/17kvug.jpg")
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")

# --- DATABASE SETUP ---
try:
    # 5-second timeout prevents the bot from hanging
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['payment_bot']
    users_col = db['users']
    cats_col = db['categories']
    client.admin.command('ping') 
except Exception as e:
    print(f"❌ DB Connection Error: {e}")
    db = None

# --- USER FLOW & BACK BUTTON FIX ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db is None:
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("⚠️ Database Offline. Check MONGO_URI.")
        return

    user = update.effective_user
    db_user = users_col.find_one({"user_id": user.id})
    
    if not db_user:
        users_col.insert_one({"user_id": user.id, "full_name": user.full_name, "is_vip": False, "is_banned": False})

    if db_user and db_user.get("is_banned"):
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("🚫 You are banned from this bot.")
        return

    # Categories Menu Logic
    categories = list(cats_col.find())
    keyboard = [[InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")] for cat in categories]
    
    msg = "<b>Welcome!</b> Please select a category to view VIP plans:"
    
    if update.callback_query:
        # Re-using the welcome image for smooth navigation
        await update.callback_query.edit_message_caption(caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# --- NAVIGATION HANDLER (FIXED BACK BUTTON) ---

async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # FIXED: back_start now properly re-runs the start logic
    if data == "back_start":
        await start(update, context)
        return

    if data.startswith("cat_"):
        cat_name = data.split("_")[1]
        cat = cats_col.find_one({"name": cat_name})
        keyboard = [[InlineKeyboardButton(f"🔹 {sub['name']}", callback_data=f"sub_{cat_name}_{sub['name']}")] for sub in cat.get('subs', [])]
        keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_start")])
        await query.edit_message_caption(caption=f"📂 <b>Category: {cat_name}</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sub_"):
        _, cat_name, sub_name = data.split("_")
        cat = cats_col.find_one({"name": cat_name})
        sub = next(s for s in cat['subs'] if s['name'] == sub_name)
        
        keyboard = [
            [InlineKeyboardButton(f"Monthly - ₹{sub['m']}", callback_data=f"plan_{sub['m']}_30_{sub_name}")],
            [InlineKeyboardButton(f"Yearly - ₹{sub['y']}", callback_data=f"plan_{sub['y']}_365_{sub_name}")],
            [InlineKeyboardButton("🔙 Back to Categories", callback_data=f"cat_{cat_name}")]
        ]
        await query.edit_message_caption(caption=f"💎 <b>{sub_name} Plans</b>\nChoose a subscription:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# --- APPROVAL & DETAILED RECEIPT ---

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Format: apprv_userid_days
    _, user_id, days = query.data.split("_")
    now = datetime.datetime.now()
    expiry = (now + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")
    
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"is_vip": True, "expiry_date": expiry}})
    
    # DIGITAL RECEIPT GENERATION
    receipt = (
        f"🧾 <b>VIP SUBSCRIPTION RECEIPT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Purchaser:</b> {update.effective_user.full_name}\n"
        f"📅 <b>Date:</b> {now.strftime('%d %B %Y')}\n"
        f"🕒 <b>Time:</b> {now.strftime('%I:%M %p')}\n"
        f"⏳ <b>Validity:</b> {days} Days\n"
        f"📅 <b>Expiry:</b> {expiry}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Welcome to the VIP family!"
    )
    
    await context.bot.send_message(chat_id=int(user_id), text=receipt, parse_mode="HTML")
    await query.edit_message_caption(caption=f"✅ Approved. User ID {user_id} is now VIP until {expiry}.")

# --- MAIN ---

def main():
    # Simple Health Check for Render
    def run_health():
        with socketserver.TCPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), http.server.SimpleHTTPRequestHandler) as h:
            h.serve_forever()
    threading.Thread(target=run_health, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_nav, pattern='^(cat_|sub_|back_)'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^apprv_'))
    
    # Conflict Killer: drop_pending_updates resets old sessions
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
