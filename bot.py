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
    settings_col = db['settings']
    cats_col = db['categories'] # New collection for dynamic plans
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

# --- USER FUNCTIONS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db is None:
        await update.message.reply_text("⚠️ Database Offline. Contact Admin.")
        return

    user = update.effective_user
    db_user = users_col.find_one({"user_id": user.id})
    
    if not db_user:
        db_user = {"user_id": user.id, "full_name": user.full_name, "username": f"@{user.username}" if user.username else "N/A", "is_vip": False, "join_date": datetime.datetime.now().strftime("%Y-%m-%d"), "expiry_date": "N/A", "is_banned": False, "warnings": 0}
        users_col.insert_one(db_user)

    if db_user.get("is_banned"):
        await update.message.reply_text("🚫 You are banned.")
        return

    if not context.user_data.get('is_auth', False) and user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nEnter passcode:", parse_mode="HTML")
        return

    # Dynamic Category Keyboard
    categories = list(cats_col.find())
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")])
    
    config = settings_col.find_one({"id": "config"}) or {"support_url": "https://t.me/YourUsername"}
    keyboard.append([InlineKeyboardButton("📞 Contact Support", url=config['support_url'])])
    
    await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Select a category to see plans:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start")
    else:
        await update.message.reply_text("❌ Incorrect passcode.")

# --- ADMIN: CATEGORY MANAGEMENT ---

@admin_only
async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addcat Anime"""
    if not context.args: return
    cat_name = context.args[0]
    if not cats_col.find_one({"name": cat_name}):
        cats_col.insert_one({"name": cat_name, "subs": []})
        await update.message.reply_text(f"✅ Category '{cat_name}' added.")
    else:
        await update.message.reply_text("❌ Category already exists.")

@admin_only
async def add_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addsub [MainCat] [SubName] [Monthly] [Yearly]"""
    if len(context.args) < 4:
        await update.message.reply_text("❌ Usage: /addsub Anime Ongoing 500 5000")
        return
    main_cat, sub_name, m_price, y_price = context.args[0], context.args[1], int(context.args[2]), int(context.args[3])
    
    sub_data = {"name": sub_name, "m": m_price, "y": y_price}
    res = cats_col.update_one({"name": main_cat}, {"$push": {"subs": sub_data}})
    
    if res.modified_count:
        await update.message.reply_text(f"✅ Sub-category '{sub_name}' added to '{main_cat}'.")
    else:
        await update.message.reply_text("❌ Main category not found.")

# --- DYNAMIC NAVIGATION ---

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("cat_"):
        cat_name = data.split("_")[1]
        cat = cats_col.find_one({"name": cat_name})
        keyboard = []
        for sub in cat['subs']:
            keyboard.append([InlineKeyboardButton(f"🔹 {sub['name']}", callback_data=f"sub_{cat_name}_{sub['name']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_start")])
        await query.edit_message_caption(caption=f"📂 <b>{cat_name}</b>\nSelect a sub-category:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sub_"):
        _, cat_name, sub_name = data.split("_")
        cat = cats_col.find_one({"name": cat_name})
        sub = next(s for s in cat['subs'] if s['name'] == sub_name)
        
        keyboard = [
            [InlineKeyboardButton(f"Monthly - ₹{sub['m']}", callback_data=f"plan_{sub['m']}_30")],
            [InlineKeyboardButton(f"Yearly - ₹{sub['y']}", callback_data=f"plan_{sub['y']}_365")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_name}")]
        ]
        await query.edit_message_caption(caption=f"💎 <b>{sub_name} Plans</b>\nChoose your subscription:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "back_start":
        # Returns user to main start screen logic
        categories = list(cats_col.find())
        keyboard = [[InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")] for cat in categories]
        await query.edit_message_caption(caption="Welcome! Select a category:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- BROADCAST & MODERATION ---

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    users = users_col.find({"is_banned": False})
    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u['user_id'], text=f"📢 <b>BROADCAST:</b>\n\n{msg}", parse_mode="HTML")
            count += 1
        except: continue
    await update.message.reply_text(f"✅ Sent to {count} users.")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_users = list(users_col.find())
    report = "📊 <b>User Report</b>\n\n"
    for u in all_users:
        status = "✨ VIP" if u.get('is_vip') else "👤 USER"
        if u.get('is_banned'): status = "🚫 BANNED"
        report += f"<b>{status}</b>: {u.get('full_name')} (<code>{u.get('user_id')}</code>)\n"
    await update.message.reply_text(report, parse_mode="HTML")

# --- PAYMENT FLOW ---

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, amount, days = query.data.split("_")
    await query.answer()
    upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
    qr = segno.make(upi_uri)
    out = io.BytesIO()
    qr.save(out, kind='png', scale=10)
    out.seek(0)
    await query.message.reply_photo(photo=out, caption=f"✅ Pay ₹{amount}\nAfter paying, send the screenshot for verification.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        keyboard = [
            [InlineKeyboardButton("✅ Approve 30 Days", callback_data=f"apprv_{update.effective_user.id}_30")],
            [InlineKeyboardButton("✅ Approve 365 Days", callback_data=f"apprv_{update.effective_user.id}_365")],
            [InlineKeyboardButton("🚫 Ban Spammer", callback_data=f"ban_{update.effective_user.id}")]
        ]
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=f"💳 Proof from {update.effective_user.id}", reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text("✅ Receipt received! Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action, user_id = data[0], int(data[1])
    if action == "apprv":
        days = int(data[2])
        expiry = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        users_col.update_one({"user_id": user_id}, {"$set": {"is_vip": True, "expiry_date": expiry}})
        await context.bot.send_message(chat_id=user_id, text=f"🎉 Approved! Exp: {expiry}")
        await query.edit_message_caption(caption=f"✅ Approved {days} Days.")
    elif action == "ban":
        users_col.update_one({"user_id": user_id}, {"$set": {"is_banned": True}})
        await query.edit_message_caption(caption="🚫 User Banned.")

# --- MAIN ---

def main():
    def run_health():
        with socketserver.TCPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), http.server.SimpleHTTPRequestHandler) as h:
            h.serve_forever()
    threading.Thread(target=run_health, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addcat", add_category))
    application.add_handler(CommandHandler("addsub", add_subcategory))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern='^(cat_|sub_|back_)'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^(apprv|ban)_'))
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
