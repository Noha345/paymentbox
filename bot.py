import os, io, asyncio, datetime
from functools import wraps
from pymongo import MongoClient
import segno

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")
BOT_PASSCODE = os.getenv("BOT_PASSCODE")

ADMIN_UPI = os.getenv("ADMIN_UPI")
PAYPAL_LINK = os.getenv("PAYPAL_LINK")
BANK_DETAILS = os.getenv("BANK_DETAILS")
WELCOME_IMAGE = os.getenv("WELCOME_IMAGE")

# ================= DB =====================
client = MongoClient(MONGO_URI)
db = client.vipbot
users = db.users
cats = db.categories

# ================= HELPERS =================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        if update.effective_user.id != ADMIN_ID:
            return
        return await func(update, context)
    return wrapper

def glass(btns):
    return InlineKeyboardMarkup(btns)

# ================= START ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user

    users.update_one(
        {"user_id": u.id},
        {"$setOnInsert": {
            "name": u.full_name,
            "is_vip": False,
            "warnings": 0,
            "banned": False
        }},
        upsert=True
    )

    if users.find_one({"user_id": u.id, "banned": True}):
        return

    if not context.user_data.get("auth") and u.id != ADMIN_ID:
        await update.message.reply_text("🔐 Enter bot password:")
        return

    kb = [
        [InlineKeyboardButton("💎 View VIP Plans", callback_data="plans")],
        [InlineKeyboardButton("📞 Contact Admin", url=f"tg://user?id={ADMIN_ID}")]
    ]

    await update.message.reply_photo(
        photo=WELCOME_IMAGE,
        caption=f"👋 Welcome *{u.full_name}*\n🆔 `{u.id}`",
        reply_markup=glass(kb),
        parse_mode="Markdown"
    )

# ================= PASSCODE =================
async def passcode(update: Update, context):
    if update.message.text == BOT_PASSCODE:
        context.user_data["auth"] = True
        await update.message.reply_text("✅ Access granted. Use /start")
    else:
        await warn(update, context)

# ================= WARN SYSTEM =============
async def warn(update, context):
    u = users.find_one({"user_id": update.effective_user.id})
    w = u.get("warnings", 0) + 1
    users.update_one({"user_id": u["user_id"]}, {"$set": {"warnings": w}})

    if w >= 3:
        users.update_one({"user_id": u["user_id"]}, {"$set": {"banned": True}})
        await context.bot.send_message(
            ADMIN_ID, f"🚫 User {u['user_id']} auto-banned (spam)"
        )
    else:
        await update.message.reply_text(f"⚠️ Warning {w}/3")

# ================= PLANS ===================
async def plans(update: Update, context):
    q = update.callback_query
    await q.answer()

    kb = []
    for c in cats.find():
        kb.append([InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"cat|{c['name']}")])

    await q.edit_message_caption("💎 Select Category", reply_markup=glass(kb))

# ================= CATEGORY =================
async def category(update: Update, context):
    q = update.callback_query
    _, cat = q.data.split("|")
    await q.answer()

    data = cats.find_one({"name": cat})
    kb = []

    for s in data.get("subs", []):
        kb.append([InlineKeyboardButton(
            f"{s['name']} – ₹{s['monthly']}/₹{s['yearly']}",
            callback_data=f"pay|{cat}|{s['name']}|{s['monthly']}|30"
        )])

    await q.edit_message_caption(f"📂 *{cat}*", reply_markup=glass(kb), parse_mode="Markdown")

# ================= PAYMENT ==================
async def payment(update, context):
    q = update.callback_query
    _, cat, sub, price, days = q.data.split("|")
    await q.answer()

    upi_uri = f"upi://pay?pa={ADMIN_UPI}&pn=VIP&am={price}&cu=INR"
    qr = segno.make(upi_uri)
    bio = io.BytesIO()
    qr.save(bio, kind="png", scale=8)
    bio.seek(0)

    kb = [
        [
            InlineKeyboardButton("🟢 Google Pay", url=upi_uri),
            InlineKeyboardButton("🟣 PhonePe", url=upi_uri)
        ],
        [InlineKeyboardButton("🔵 Paytm", url=upi_uri)],
        [InlineKeyboardButton("💳 PayPal", url=PAYPAL_LINK)],
        [InlineKeyboardButton("🏦 Bank Transfer", callback_data="bank")]
    ]

    await q.message.reply_photo(
        bio,
        caption=(
            f"💎 *VIP Payment*\n\n"
            f"📦 Plan: `{sub}`\n"
            f"💰 Amount: `₹{price}`\n"
            f"📅 Validity: `{days} days`\n\n"
            f"📸 Send payment screenshot after paying"
        ),
        reply_markup=glass(kb),
        parse_mode="Markdown"
    )

# ================= BANK ====================
async def bank(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(f"🏦 *Bank Details*\n\n{BANK_DETAILS}", parse_mode="Markdown")

# ================= RECEIPT =================
async def receipt(update, context):
    await context.bot.send_photo(
        ADMIN_ID,
        update.message.photo[-1].file_id,
        caption=f"🧾 Payment proof from {update.effective_user.id}",
        reply_markup=glass([
            [InlineKeyboardButton("✅ Approve 30 Days", callback_data=f"ok|{update.effective_user.id}|30")],
            [InlineKeyboardButton("✅ Approve 365 Days", callback_data=f"ok|{update.effective_user.id}|365")]
        ])
    )
    await update.message.reply_text("⏳ Waiting for admin approval")

# ================= APPROVAL =================
async def approve(update, context):
    q = update.callback_query
    _, uid, days = q.data.split("|")
    uid, days = int(uid), int(days)

    now = datetime.datetime.now()
    expiry = now + datetime.timedelta(days=days)

    users.update_one(
        {"user_id": uid},
        {"$set": {"is_vip": True, "expiry": expiry}}
    )

    invoice = (
        f"🧾 *VIP INVOICE*\n\n"
        f"👤 User ID: `{uid}`\n"
        f"📅 Purchased: `{now}`\n"
        f"⌛ Validity: `{days} days`\n"
        f"⛔ Expires: `{expiry}`"
    )

    await context.bot.send_message(uid, invoice, parse_mode="Markdown")
    await q.edit_message_caption("✅ Approved")

# ================= EXPIRY JOB ===============
async def expiry_job(app):
    while True:
        now = datetime.datetime.now()
        for u in users.find({"is_vip": True}):
            if u["expiry"] <= now:
                users.update_one({"user_id": u["user_id"]}, {"$set": {"is_vip": False}})
                await app.bot.send_message(u["user_id"], "❌ VIP expired")
                await app.bot.send_message(ADMIN_ID, f"⏰ VIP expired: {u['user_id']}")
        await asyncio.sleep(3600)

# ================= MAIN =====================
async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(plans, pattern="plans"))
    app.add_handler(CallbackQueryHandler(category, pattern="cat\\|"))
    app.add_handler(CallbackQueryHandler(payment, pattern="pay\\|"))
    app.add_handler(CallbackQueryHandler(bank, pattern="bank"))
    app.add_handler(CallbackQueryHandler(approve, pattern="ok\\|"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, passcode))
    app.add_handler(MessageHandler(filters.PHOTO, receipt))

    asyncio.create_task(expiry_job(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
    
