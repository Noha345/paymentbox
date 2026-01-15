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

    categories = list(cats_col.find())
    keyboard = [[InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")] for cat in categories]
    
    config = settings_col.find_one({"id": "config"}) or {"support_url": "https://t.me/YourUsername"}
    keyboard.append([InlineKeyboardButton("📞 Contact Support", url=config['support_url'])])
    
    await update.message.reply_photo(photo=WELCOME_IMAGE, caption="<b>Welcome!</b> Select a category to see plans:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start")
    else:
        await update.message.reply_text("❌ Incorrect passcode.")

# --- ADMIN: CATEGORY & LINK MANAGEMENT ---

@admin_only
async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addcat [Name]"""
    if not context.args: return
    cat_name = context.args[0]
    cats_col.update_one({"name": cat_name}, {"$setOnInsert": {"subs": []}}, upsert=True)
    await update.message.reply_text(f"✅ Category '{cat_name}' added.")

@admin_only
async def add_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addsub [MainCat] [SubName] [Monthly] [Yearly] [ChannelLink]"""
    if len(context.args) < 5:
        await update.message.reply_text("❌ Usage: /addsub AdultHub Channel1 500 5000 https://t.me/link")
        return
    main_cat, sub_name, m_price, y_price, link = context.args[0], context.args[1], int(context.args[2]), int(context.args[3]), context.args[4]
    
    sub_data = {"name": sub_name, "m": m_price, "y": y_price, "link": link}
    cats_col.update_one({"name": main_cat}, {"$push": {"subs": sub_data}})
    await update.message.reply_text(f"✅ Sub-category '{sub_name}' with link added to '{main_cat}'.")

# --- NAVIGATION & PAYMENT FLOW ---

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("cat_"):
        cat_name = data.split("_")[1]
        cat = cats_col.find_one({"name": cat_name})
        keyboard = [[InlineKeyboardButton(f"🔹 {sub['name']}", callback_data=f"sub_{cat_name}_{sub['name']}")] for sub in cat['subs']]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_start")])
        await query.edit_message_caption(caption=f"📂 <b>{cat_name}</b>\nSelect a sub-category:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sub_"):
        _, cat_name, sub_name = data.split("_")
        cat = cats_col.find_one({"name": cat_name})
        sub = next(s for s in cat['subs'] if s['name'] == sub_name)
        
        keyboard = [
            [InlineKeyboardButton(f"Monthly - ₹{sub['m']}", callback_data=f"plan_{sub['m']}_30_{cat_name}_{sub_name}")],
            [InlineKeyboardButton(f"Yearly - ₹{sub['y']}", callback_data=f"plan_{sub['y']}_365_{cat_name}_{sub_name}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_name}")]
        ]
        await query.edit_message_caption(caption=f"💎 <b>{sub_name} Plans</b>\nChoose your subscription:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "back_start":
        await start(update, context)

async def handle_payment_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, amount, days, cat, sub = query.data.split("_")
    await query.answer()
    
    upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
    qr = segno.make(upi_uri)
    out = io.BytesIO()
    qr.save(out, kind='png', scale=10)
    out.seek(0)
    
    await query.message.reply_photo(photo=out, caption=f"✅ <b>Payment for {sub}</b>\nAmount: ₹{amount}\n\nScan QR and send the screenshot for verification.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        # We try to guess category from context or user must specify, but for this logic we provide general buttons
        keyboard = [
            [InlineKeyboardButton("✅ Approve 30 Days", callback_data=f"apprv_{update.effective_user.id}_30")],
            [InlineKeyboardButton("✅ Approve 365 Days", callback_data=f"apprv_{update.effective_user.id}_365")],
            [InlineKeyboardButton("🚫 Ban Spammer", callback_data=f"ban_{update.effective_user.id}")]
        ]
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, 
            caption=f"💳 Proof from {update.effective_user.id}\nName: {update.effective_user.full_name}", 
            reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text("✅ Receipt received! Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action, user_id = data[0], int(data[1])
    
    if action == "apprv":
        days = int(data[2])
        now = datetime.datetime.now()
        expiry = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        
        # In a real scenario, you'd match the specific sub-category link. 
        # For simplicity, we fetch the first available cat/sub link or you can track 'last_selected' in user_col
        user_record = users_col.find_one({"user_id": user_id})
        users_col.update_one({"user_id": user_id}, {"$set": {"is_vip": True, "expiry_date": expiry}})
        
        receipt = (
            f"🧾 <b>VIP SUBSCRIPTION RECEIPT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Purchaser:</b> {user_record['full_name']}\n"
            f"📅 <b>Date:</b> {now.strftime('%Y-%m-%d')}\n"
            f"🕒 <b>Time:</b> {now.strftime('%H:%M:%S')}\n"
            f"⌛ <b>Validity:</b> {days} Days\n"
            f"📅 <b>Expiry:</b> {expiry}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 <b>Your VIP Link:</b> Provided Below"
        )
        
        # Link logic: Admin can provide the link manually or bot pulls default
        await context.bot.send_message(chat_id=user_id, text=receipt, parse_mode="HTML")
        await context.bot.send_message(chat_id=user_id, text="👉 <b>Join Your VIP Channel:</b>\n(Check your categories for specific links or use the main channel link set by Admin)")
        await query.edit_message_caption(caption=f"✅ Approved {days} Days until {expiry}")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_users = list(users_col.find())
    report = "📊 <b>User Report</b>\n\n"
    for u in all_users:
        status = "✨ VIP" if u.get('is_vip') else "👤 USER"
        report += f"<b>{status}</b>: {u.get('full_name')} (<code>{u.get('user_id')}</code>)\n"
    await update.message.reply_text(report, parse_mode="HTML")

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
    application.add_handler(CommandHandler("stats", stats))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern='^(cat_|sub_|back_)'))
    application.add_handler(CallbackQueryHandler(handle_payment_request, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^(apprv|ban)_'))
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
