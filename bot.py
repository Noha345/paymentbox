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
# Automatically handles both MONGO and MANGO naming from your dashboard
MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MANGO_URI")
ADMIN_UPI = os.environ.get("ADMIN_UPI", "yourname@upi")
WELCOME_IMAGE = os.environ.get("WELCOME_IMAGE", "https://files.catbox.moe/17kvug.jpg")
BOT_PASSCODE = os.environ.get("BOT_PASSCODE", "1234")

# --- DATABASE SETUP ---
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['payment_bot']
    users_col = db['users']
    cats_col = db['categories'] # For multiple sub-categories
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

# --- USER FLOW ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db is None:
        await update.message.reply_text("⚠️ Database Offline. Contact Admin.")
        return

    user = update.effective_user
    db_user = users_col.find_one({"user_id": user.id})
    
    if not db_user:
        db_user = {"user_id": user.id, "full_name": user.full_name, "is_vip": False, "is_banned": False}
        users_col.insert_one(db_user)

    if db_user.get("is_banned"):
        await update.message.reply_text("🚫 You are banned.")
        return

    if not context.user_data.get('is_auth', False) and user.id != ADMIN_ID:
        await update.message.reply_text("🔐 <b>Bot is Locked.</b>\nEnter passcode:", parse_mode="HTML")
        return

    # Fetch all categories to build the main menu
    categories = list(cats_col.find())
    keyboard = [[InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"cat_{cat['name']}")] for cat in categories]
    
    msg = "<b>Welcome!</b> Choose a category to see plans:"
    if update.callback_query:
        await update.callback_query.edit_message_caption(caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.message.reply_photo(photo=WELCOME_IMAGE, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == BOT_PASSCODE:
        context.user_data['is_auth'] = True
        await update.message.reply_text("✅ Access Granted! Use /start")
    else:
        await update.message.reply_text("❌ Incorrect passcode.")

# --- NAVIGATION HANDLER (FIXED BACK BUTTON) ---

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # FIXED: Back button now routes correctly back to the start menu
    if data == "back_start":
        await start(update, context)
        return

    if data.startswith("cat_"):
        cat_name = data.split("_")[1]
        cat = cats_col.find_one({"name": cat_name})
        keyboard = [[InlineKeyboardButton(f"🔹 {sub['name']}", callback_data=f"sub_{cat_name}_{sub['name']}")] for sub in cat.get('subs', [])]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_start")])
        await query.edit_message_caption(caption=f"📂 <b>{cat_name}</b>\nSelect a sub-category:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sub_"):
        _, cat_name, sub_name = data.split("_")
        cat = cats_col.find_one({"name": cat_name})
        sub = next(s for s in cat['subs'] if s['name'] == sub_name)
        
        keyboard = [
            [InlineKeyboardButton(f"Monthly - ₹{sub['m']}", callback_data=f"plan_{sub['m']}_30_{sub_name}")],
            [InlineKeyboardButton(f"Yearly - ₹{sub['y']}", callback_data=f"plan_{sub['y']}_365_{sub_name}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_name}")]
        ]
        await query.edit_message_caption(caption=f"💎 <b>{sub_name} Plans</b>\nChoose subscription:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# --- ADMIN MANAGEMENT ---

@admin_only
async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addcat Anime"""
    if not context.args: return
    cat_name = context.args[0]
    cats_col.update_one({"name": cat_name}, {"$setOnInsert": {"subs": []}}, upsert=True)
    await update.message.reply_text(f"✅ Category '{cat_name}' added.")

@admin_only
async def add_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addsub Anime Ongoing 499 4499 https://t.me/link"""
    if len(context.args) < 5:
        await update.message.reply_text("❌ Usage: /addsub [MainCat] [SubName] [Monthly] [Yearly] [Link]")
        return
    main_cat, sub_name, m_price, y_price, link = context.args[0], context.args[1], int(context.args[2]), int(context.args[3]), context.args[4]
    
    sub_data = {"name": sub_name, "m": m_price, "y": y_price, "link": link}
    # This $push allows adding multiple sub-categories to the same main category
    cats_col.update_one({"name": main_cat}, {"$push": {"subs": sub_data}})
    await update.message.reply_text(f"✅ Sub-category '{sub_name}' added to '{main_cat}'.")

# --- BROADCAST & MODERATION ---

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /broadcast Hello"""
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

# --- PAYMENT FLOW ---

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, amount, days, sub_name = query.data.split("_")
    
    upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=Admin&am={amount}&cu=INR"
    qr = segno.make(upi_uri)
    out = io.BytesIO()
    qr.save(out, kind='png', scale=10)
    out.seek(0)
    
    await query.message.reply_photo(photo=out, caption=f"✅ <b>Pay ₹{amount} for {sub_name}</b>\nSend screenshot after paying.")

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        keyboard = [
            [InlineKeyboardButton("✅ Approve 30 Days", callback_data=f"apprv_{update.effective_user.id}_30")],
            [InlineKeyboardButton("✅ Approve 365 Days", callback_data=f"apprv_{update.effective_user.id}_365")]
        ]
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, 
                                     caption=f"💳 Proof from {update.effective_user.id}", reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text("✅ Receipt received! Admin is verifying.")

async def admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, user_id, days = query.data.split("_")
    now = datetime.datetime.now()
    expiry = (now + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")
    
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"is_vip": True, "expiry_date": expiry}})
    
    # DIGITAL RECEIPT WITH PURCHASER NAME, DATE, AND TIME
    receipt = (
        f"🧾 <b>VIP PURCHASE RECEIPT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Purchaser:</b> {update.effective_user.full_name}\n"
        f"📅 <b>Date:</b> {now.strftime('%d %b %Y')}\n"
        f"🕒 <b>Time:</b> {now.strftime('%I:%M %p')}\n"
        f"⏳ <b>Validity:</b> {days} Days\n"
        f"📅 <b>Expiry:</b> {expiry}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    await context.bot.send_message(chat_id=int(user_id), text=receipt, parse_mode="HTML")
    await query.edit_message_caption(caption=f"✅ Approved until {expiry}")

# --- MAIN ---

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addcat", add_category))
    application.add_handler(CommandHandler("addsub", add_subcategory))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode))
    application.add_handler(MessageHandler(filters.PHOTO, verify_payment))
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern='^(cat_|sub_|back_)'))
    application.add_handler(CallbackQueryHandler(handle_payment, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(admin_approval, pattern='^apprv_'))
    
    # Clears old instances to fix Conflict error
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
