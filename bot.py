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
MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MANGO_URI")
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
WELCOME_IMAGE = "https://files.catbox.moe/17kvug.jpg"
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")

# --- DATABASE SETUP ---
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['payment_bot']
    users_col = db['users']
    cats_col = db['categories']
    client.admin.command('ping') 
except Exception as e:
    print(f"❌ DB Error: {e}")
    db = None

# --- ADMIN DECORATOR ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Access Denied.")
            return
        return await func(update, context)
    return wrapper

# --- USER FLOW & PASSCODE FIX ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db is None:
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("⚠️ Database Offline. Check MONGO_URI.")
        return

    user = update.effective_user
    db_user = users_col.find_one({"user_id": user.id})
    if not db_user:
        users_col.insert_one({"user_id": user.id, "full_name": user.full_name, "is_vip": False, "is_banned": False})

    # Passcode Auth logic
    if not context.user_data.get('is_auth', False) and user.id != ADMIN_ID:
        await (update.callback_query.message if update.callback_query else update.message).reply_text("🔐 Enter passcode:")
        return

    # Categories Menu
    categories = list(cats_col.find())
    keyboard = [[InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")] for cat in categories]
    
    msg = "<b>Welcome!</b> Select a category to view VIP plans:"
    if update.callback_query:
        await update.callback_query.edit_message_caption(caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle passcode entry
    if not context.user_data.get('is_auth', False):
        if update.message.text == BOT_PASSCODE:
            context.user_data['is_auth'] = True
            await update.message.reply_text("✅ Access Granted! Use /start")
        else:
            await update.message.reply_text("❌ Incorrect passcode.")
        return

# --- NAVIGATION HANDLER (FIXED BACK BUTTON) ---

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # FIXED: Back button now routes correctly
    if data == "back_start":
        await start(update, context)
        return

    if data.startswith("cat_"):
        cat_name = data.split("_")[1]
        cat = cats_col.find_one({"name": cat_name})
        keyboard = [[InlineKeyboardButton(f"🔹 {sub['name']}", callback_data=f"sub_{cat_name}_{sub['name']}")] for sub in cat.get('subs', [])]
        keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_start")])
        await query.edit_message_caption(caption=f"📂 <b>{cat_name}</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sub_"):
        _, cat_name, sub_name = data.split("_")
        cat = cats_col.find_one({"name": cat_name})
        sub = next(s for s in cat['subs'] if s['name'] == sub_name)
        keyboard = [[InlineKeyboardButton(f"Monthly - ₹{sub['m']}", callback_data=f"plan_{sub['m']}_30_{sub_name}")],
                    [InlineKeyboardButton(f"Yearly - ₹{sub['y']}", callback_data=f"plan_{sub['y']}_365_{sub_name}")],
                    [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_name}")]]
        await query.edit_message_caption(caption=f"💎 <b>{sub_name} Plans</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# --- ADMIN COMMANDS ---

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /broadcast Hello"""
    if not context.args: return
    msg = " ".join(context.args)
    users = users_col.find({"is_banned": False})
    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u['user_id'], text=f"📢 <b>ALERT:</b>\n\n{msg}", parse_mode="HTML")
            count += 1
        except: continue
    await update.message.reply_text(f"✅ Sent to {count} users.")

@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /ban [UserID]"""
    if not context.args: return
    uid = int(context.args[0])
    users_col.update_one({"user_id": uid}, {"$set": {"is_banned": True}})
    await update.message.reply_text(f"🚫 User {uid} Banned.")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users"""
    all_users = list(users_col.find())
    report = "📊 <b>User Report</b>\n\n"
    for u in all_users:
        status = "✨ VIP" if u.get('is_vip') else "👤 USER"
        if u.get('is_banned'): status = "🚫 BANNED"
        report += f"{status}: {u.get('full_name')} (<code>{u.get('user_id')}</code>)\n"
    await update.message.reply_text(report, parse_mode="HTML")

# --- MAIN ---

def main():
    def run_health():
        with socketserver.TCPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), http.server.SimpleHTTPRequestHandler) as h:
            h.serve_forever()
    threading.Thread(target=run_health, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("stats", stats))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern='^(cat_|sub_|back_)'))
    
    # Conflict Killer: drop_pending_updates resets old sessions
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
