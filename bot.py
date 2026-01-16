import logging
import asyncio
import io
import os
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient
import qrcode
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))
ADMIN_UPI = os.getenv("ADMIN_UPI", "yourname@upi")
WELCOME_IMAGE = os.getenv("WELCOME_IMAGE", "https://files.catbox.moe/17kvug.jpg")
BOT_PASSCODE = os.getenv("BOT_PASSCODE", "1234")

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["VipBotDB"]
settings_col = db["settings"]
users_col = db["users"]
subs_col = db["subscriptions"]

# ================= BOT =================
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= DATA =================
DEFAULT_CATEGORIES = {
    "adult": {"name": "🔞 Adult Hub", "price": "10 INR", "link": "https://t.me/+pDemZzNHnsU5MTg1"},
    "movie": {"name": "🎬 Movies & Series", "price": "100 INR", "link": "https://t.me/+ExampleLink"},
    "coding": {"name": "💻 Coding Resources", "price": "200 INR", "link": "https://t.me/+ExampleLink"},
    "gaming": {"name": "🎮 Gaming & Mods", "price": "120 INR", "link": "https://t.me/+ExampleLink"}
}
#clsss userstate 
class UserState(StatesGroup):
    waiting_for_proof = State()
    waiting_for_passcode = State()
    waiting_for_help = State()

    add_cat_key = State()
    add_cat_name = State()
    add_cat_price = State()
    add_cat_link = State()

    edit_cat_select = State()
    edit_cat_field = State()
    edit_cat_value = State()

    selecting_category = State()   # 👈 NEW
    selecting_plan = State()       # 👈 NEW
    delete_cat = State()
    admin_cat_select = State()

    add_plan_label = State()
    add_plan_days = State()
    add_plan_price = State()

    edit_plan_select = State()
    edit_plan_field = State()
    edit_plan_value = State()

    delete_plan = State()

    set_channel_id = State()
    set_group_id = State()

# ================= HELPERS =================
async def get_settings():
    s = await settings_col.find_one({"_id": "main"})
    if not s:
        s = {
            "_id": "main",
            "upi_id": "nohasheldendsouza@oksbi",
            "categories": DEFAULT_CATEGORIES
        }
        await settings_col.insert_one(s)
    return s

def generate_upi_qr(upi):
    qr = qrcode.make(f"upi://pay?pa={upi}&cu=INR")
    bio = io.BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ================= WEB =================
async def health(request):
    return web.Response(text="Bot running")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# ================= HANDLERS =================

@dp.message(CommandStart())
async def start_cmd(m: types.Message, state: FSMContext):
    user = await users_col.find_one({"user_id": m.from_user.id})

    # NEW USER → PASSCODE REQUIRED
    if not user or not user.get("verified"):
        await state.set_state(UserState.waiting_for_passcode)
        return await m.answer(
            "🔐 Access Protected\n\nPlease enter the bot passcode:"
        )

    # VERIFIED USER MENU
    kb = [
        [
            types.KeyboardButton(text="💎 Buy VIP Membership"),
            types.KeyboardButton(text="❓ Help")
        ]
    ]

    # ADMIN EXTRA BUTTON
    if m.from_user.id == ADMIN_ID:
        kb.append([types.KeyboardButton(text="⚙️ Admin Panel")])

    await m.answer_photo(
        photo=WELCOME_IMAGE,
        caption="👋 Welcome to the Premium Bot!",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=kb,
            resize_keyboard=True
        )
    )

@dp.message(UserState.waiting_for_passcode)
async def check_passcode(m: types.Message, state: FSMContext):
    if m.text != BOT_PASSCODE:
        return await m.answer("❌ Wrong passcode. Try again.")

    # Correct passcode
    await users_col.update_one(
    {"user_id": m.from_user.id},
    {
        "$set": {
            "username": m.from_user.username,
            "verified": True,
            "joined_at": datetime.utcnow().strftime("%Y-%m-%d")
        }
    },
    upsert=True
    )

    await state.clear()

    kb = [
        [
            types.KeyboardButton(text="💎 Buy VIP Membership"),
            types.KeyboardButton(text="❓ Help")
        ]
    ]

    await m.answer_photo(
        photo=WELCOME_IMAGE,
        caption="✅ *Access Granted!*\n\nWelcome to the Premium Bot 🎉",
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=kb,
            resize_keyboard=True
        )
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def show_categories(m: types.Message):
    s = await get_settings()
    kb = InlineKeyboardBuilder()
    for k, v in s["categories"].items():
        kb.button(text=f"{v['name']} ({v['price']})", callback_data=f"cat_{k}")
    kb.adjust(1)
    await m.answer("Select category:", reply_markup=kb.as_markup())

@dp.message(F.text == "❓ Help")
async def help_start(m: types.Message, state: FSMContext):
    await state.set_state(UserState.waiting_for_help)
    await m.answer(
        "🆘 *Support*\n\nApni problem clearly likho.\nAdmin jaldi reply karega 🙂",
        parse_mode="Markdown"
    )


@dp.message(F.text == "⚙️ Admin Panel")
async def admin_panel(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    kb = [
        [types.KeyboardButton(text="👥 Users")],
        [types.KeyboardButton(text="💰 Manage Categories")],
        [types.KeyboardButton(text="📢 Force Subscribe")],
        [types.KeyboardButton(text="⬅️ Back")]
    ]

    await m.answer(
        "⚙️ *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=kb, resize_keyboard=True
        )
    )
    
@dp.message(UserState.waiting_for_help)
async def send_help_to_admin(m: types.Message, state: FSMContext):
    await state.clear()

    header = (
        "🆘 *Help Request*\n\n"
        f"👤 User: {m.from_user.full_name}\n"
        f"🆔 User ID: `{m.from_user.id}`\n\n"
        "📩 Message:"
    )

    if m.photo:
        await bot.send_photo(
            ADMIN_ID,
            m.photo[-1].file_id,
            caption=f"{header}",
            parse_mode="Markdown"
        )
    else:
        await bot.send_message(
            ADMIN_ID,
            f"{header}\n{m.text}",
            parse_mode="Markdown"
        )

    await m.answer("✅ Message admin ko bhej diya gaya hai.\nPlease wait for reply ⏳")

@dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply_to_user(m: types.Message):
    original = m.reply_to_message.text or m.reply_to_message.caption
    if not original or "User ID:" not in original:
        return

    try:
        user_id = int(original.split("User ID:")[1].split()[0].replace("`", ""))
    except:
        return

    await bot.send_message(
        user_id,
        f"💬 *Admin Reply:*\n\n{m.text}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "⬅️ Back")
async def back_btn(m: types.Message):
    kb = [
        [
            types.KeyboardButton(text="💎 Buy VIP Membership"),
            types.KeyboardButton(text="❓ Help")
        ]
    ]
    if m.from_user.id == ADMIN_ID:
        kb.append([types.KeyboardButton(text="⚙️ Admin Panel")])

    await m.answer(
        "⬅️ Back to main menu",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=kb, resize_keyboard=True
        )
    )


@dp.callback_query(F.data.startswith("cat_"))
async def select_category(c: types.CallbackQuery, state: FSMContext):
    cat_key = c.data.split("_", 1)[1]
    settings = await get_settings()
    category = settings["categories"].get(cat_key)

    if not category:
        return await c.answer("Category not found", show_alert=True)

    plans = category.get("plans")
    if not plans:
        return await c.answer("No plans available. Contact admin.", show_alert=True)

    await state.update_data(category=cat_key)
    await state.set_state(UserState.selecting_plan)

    kb = InlineKeyboardBuilder()
    for plan_id, plan in plans.items():
        kb.button(
            text=f"{category['name']} – {plan['label']} – {plan['price']}",
            callback_data=f"plan_{plan_id}"
        )

    kb.button(text="⬅️ Back", callback_data="back_to_categories")
    kb.adjust(1)

    await c.message.edit_text(
        f"📦 *Select a Plan for {category['name']}*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await get_settings()

    kb = InlineKeyboardBuilder()
    for key, data in settings["categories"].items():
        kb.button(text=data["name"], callback_data=f"cat_{key}")
    kb.adjust(1)

    await c.message.edit_text(
        "✨ *Select a VIP Category:*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

#plan working with inline button 

@dp.callback_query(F.data.startswith("plan_"))
async def select_plan(c: types.CallbackQuery, state: FSMContext):
    plan_id = c.data.split("_", 1)[1]
    data = await state.get_data()
    cat_key = data.get("category")

    settings = await get_settings()
    category = settings["categories"].get(cat_key)
    plan = category["plans"].get(plan_id)

    if not plan:
        return await c.answer("Plan not found", show_alert=True)

    # Save selected plan
    await state.update_data(plan_id=plan_id)

    # ✅ INLINE BUTTONS
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Proceed to Payment",
                    callback_data="proceed_payment"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data=f"cat_{cat_key}"
                )
            ]
        ]
    )

    await c.message.edit_text(
        f"✅ *Plan Selected*\n\n"
        f"📂 Category: {category['name']}\n"
        f"📦 Plan: {plan['label']}\n"
        f"💰 Price: {plan['price']}\n\n"
        f"Tap below to continue ⬇️",
        parse_mode="Markdown",
        reply_markup=kb
    )
    
#proceed payment 

@dp.callback_query(F.data == "proceed_payment")
async def proceed_payment(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cat = data.get("category")
    plan_id = data.get("plan_id")

    if not cat or not plan_id:
        return await c.answer("Session expired. Please try again.", show_alert=True)

    settings = await get_settings()
    category = settings["categories"][cat]
    plan = category["plans"][plan_id]

    qr = generate_upi_qr(settings["upi_id"])

    await c.message.answer_photo(
        types.BufferedInputFile(qr.getvalue(), "upi.png"),
        caption=(
            "💳 *Payment Instructions*\n\n"
            f"📂 Category: {category['name']}\n"
            f"📦 Plan: {plan['label']}\n"
            f"💰 Price: {plan['price']}\n\n"
            "✅ Pay via UPI\n"
            "📸 Then send *payment screenshot / proof* here"
        ),
        parse_mode="Markdown"
    )

    await state.set_state(UserState.waiting_for_proof)
    await c.answer()

# ================= PROOF =================
@dp.message(UserState.waiting_for_proof)
async def receive_proof(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    cat = data.get("category")
    plan_id = data.get("plan_id")

    if not cat or not plan_id:
        return await m.answer("❌ Session expired. Please try again.")

    admin_kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(
            text="✅ Approve",
            callback_data=f"approve_{m.from_user.id}_{cat}_{plan_id}"
        ),
        types.InlineKeyboardButton(
            text="❌ Reject",
            callback_data=f"reject_{m.from_user.id}"
        )
    ]])

    caption = (
        "🧾 *Payment Proof*\n\n"
        f"👤 User: {m.from_user.full_name}\n"
        f"🆔 ID: `{m.from_user.id}`\n"
        f"📂 Category: `{cat}`\n"
        f"📦 Plan: `{plan_id}`"
    )

    if m.photo:
        await bot.send_photo(
            ADMIN_ID,
            m.photo[-1].file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=admin_kb
        )
    else:
        await bot.send_message(
            ADMIN_ID,
            caption + f"\n\n📄 Message:\n{m.text}",
            parse_mode="Markdown",
            reply_markup=admin_kb
        )

    await m.answer("✅ Proof sent to admin. Please wait for approval.")
    
# ================= ADMIN ACTIONS =================

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(c: types.CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return

    _, uid, cat, plan_id = c.data.split("_")
    uid = int(uid)

    settings = await get_settings()
    category = settings["categories"].get(cat)
    plan = category["plans"].get(plan_id)

    days = plan["days"]
    purchase_date = datetime.utcnow()
    expires_at = purchase_date + timedelta(days=days)

    # Save subscription
    await subs_col.insert_one({
        "user_id": uid,
        "category": cat,
        "plan_id": plan_id,
        "expires_at": expires_at,
        "reminder_sent": False,
        "status": "active"
    })

    # Try to add user
    added = False
    invite_text = "Access granted automatically"

    try:
        if category.get("channel_id"):
            await bot.add_chat_members(category["channel_id"], uid)
            added = True

        if category.get("group_id"):
            await bot.add_chat_members(category["group_id"], uid)
            added = True
    except:
        pass

    # Privacy fallback → invite
    if not added:
        if category.get("channel_id"):
            link = await bot.create_chat_invite_link(category["channel_id"], member_limit=1)
            invite_text = link.invite_link
            await bot.send_message(uid, f"🔗 Join Channel:\n{invite_text}")

        if category.get("group_id"):
            link = await bot.create_chat_invite_link(category["group_id"], member_limit=1)
            invite_text = link.invite_link
            await bot.send_message(uid, f"🔗 Join Group:\n{invite_text}")

    # Extract purchaser name SAFELY
    user_name = "Unknown User"
    try:
        if c.message.caption and "User:" in c.message.caption:
            user_name = c.message.caption.split("User:")[1].splitlines()[0].strip()
    except:
        pass

    # VIP RECEIPT
    receipt = (
        "🧾 <b>VIP SUBSCRIPTION RECEIPT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Purchaser:</b> {user_name}\n"
        f"🆔 <b>User ID:</b> {uid}\n"
        f"📂 <b>Category:</b> {category['name']}\n"
        f"🔹 <b>Plan:</b> {plan['label']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Purchase Date:</b> {purchase_date.strftime('%d %b %Y')}\n"
        f"🕒 <b>Time:</b> {purchase_date.strftime('%I:%M %p')}\n"
        f"⏳ <b>Validity:</b> {days} Days\n"
        f"📅 <b>Expiry Date:</b> {expires_at.strftime('%d %b %Y')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎉 <b>Status:</b> Payment Verified & Active\n"
        f"👉 <b>Your VIP Link:</b> {invite_text}"
    )

    await bot.send_message(uid, receipt, parse_mode="HTML")
    await c.message.edit_caption("✅ Approved & VIP Activated")
    
@dp.callback_query(F.data.startswith("reject_"))
async def reject(c: types.CallbackQuery):
    uid = c.data.split("_")[1]
    await bot.send_message(int(uid), "❌ Payment rejected")
    await c.message.edit_caption("❌ Rejected")

       #users#
@dp.message(F.text == "👥 Users")
async def admin_users(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    cursor = users_col.find()
    text = "👥 USERS LIST\n\n"

    async for u in cursor:
        text += (
            f"Name: {u.get('username', 'N/A')}\n"
            f"User ID: {u['user_id']}\n"
            f"Joined: {u.get('joined_at', 'N/A')}\n\n"
        )

        # avoid message too long
        if len(text) > 3500:
            await m.answer(text)
            text = ""

    if text:
        await m.answer(text)

    await m.answer(
        "✉️ Send message:\n"
        "/msg user_id your message\n"
        "/msg @username your message"
    )

#manage category 
@dp.message(F.text == "💰 Manage Categories")
async def admin_manage_categories(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return

    settings = await get_settings()
    kb = InlineKeyboardBuilder()

    for key, cat in settings["categories"].items():
        kb.button(text=cat["name"], callback_data=f"admin_cat_{key}")

    kb.adjust(1)

    await m.answer(
        "💰 *Select Category to Manage*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("admin_cat_"))
async def admin_cat_actions(c: types.CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return

    cat_key = c.data.split("_", 2)[2]
    await state.update_data(admin_category=cat_key)

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Add Plan", callback_data="admin_add_plan")
    kb.button(text="✏️ Edit Plan", callback_data="admin_edit_plan")
    kb.button(text="🗑 Delete Plan", callback_data="admin_delete_plan")
    kb.button(text="🔗 Set Channel ID", callback_data="admin_set_channel")
    kb.button(text="👥 Set Group ID", callback_data="admin_set_group")
    kb.button(text="⬅️ Back", callback_data="admin_back_categories")
    kb.adjust(1)

    await c.message.edit_text(
        "⚙️ *Category Management*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "admin_add_plan")
async def admin_add_plan_start(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserState.add_plan_label)
    await c.message.edit_text("Enter *plan label* (example: 30 Days)", parse_mode="Markdown")

@dp.message(UserState.add_plan_label)
async def admin_add_plan_label(m: types.Message, state: FSMContext):
    await state.update_data(plan_label=m.text)
    await state.set_state(UserState.add_plan_days)
    await m.answer("Enter *plan duration in days* (number)")

@dp.message(UserState.add_plan_days)
async def admin_add_plan_days(m: types.Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Please enter number of days")
    await state.update_data(plan_days=int(m.text))
    await state.set_state(UserState.add_plan_price)
    await m.answer("Enter *price* (example: 199 INR)")

@dp.message(UserState.add_plan_price)
async def admin_add_plan_price(m: types.Message, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]

    plan_id = f"p{int(asyncio.get_event_loop().time())}"

    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {
            f"categories.{cat}.plans.{plan_id}": {
                "label": data["plan_label"],
                "days": data["plan_days"],
                "price": m.text
            }
        }}
    )

    await state.clear()
    await m.answer("✅ Plan added successfully")

@dp.callback_query(F.data == "admin_edit_plan")
async def admin_edit_plan(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]

    settings = await get_settings()
    plans = settings["categories"][cat].get("plans", {})

    kb = InlineKeyboardBuilder()
    for pid, plan in plans.items():
        kb.button(
            text=f"{plan['label']} – {plan['price']}",
            callback_data=f"editplan_{pid}"
        )

    kb.button(text="⬅️ Back", callback_data="admin_cat_back")
    kb.adjust(1)

    await c.message.edit_text(
        "✏️ *Select a plan to edit*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("editplan_"))
async def edit_plan_fields(c: types.CallbackQuery, state: FSMContext):
    plan_id = c.data.split("_", 1)[1]
    await state.update_data(edit_plan_id=plan_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Label", callback_data="editfield_label")],
        [InlineKeyboardButton(text="💰 Price", callback_data="editfield_price")],
        [InlineKeyboardButton(text="⏳ Days", callback_data="editfield_days")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_edit_plan")]
    ])

    await c.message.edit_text(
        "✏️ *What do you want to edit?*",
        parse_mode="Markdown",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("editfield_"))
async def ask_new_value(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_", 1)[1]
    await state.update_data(edit_field=field)

    await c.message.edit_text(
        f"✍️ Send new value for *{field}*",
        parse_mode="Markdown"
    )

@dp.message()
async def save_edit_plan(m: types.Message, state: FSMContext):
    data = await state.get_data()

    if "edit_plan_id" not in data or "edit_field" not in data:
        return

    cat = data["admin_category"]
    pid = data["edit_plan_id"]
    field = data["edit_field"]

    settings = await get_settings()
    plan = settings["categories"][cat]["plans"][pid]

    old_value = plan[field]
    new_value = int(m.text) if field == "days" else m.text

    # Update DB
    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{cat}.plans.{pid}.{field}": new_value}}
    )

    # Clear only edit-related state
    await state.update_data(edit_plan_id=None, edit_field=None)

    # ✅ Confirmation message
    await m.answer(
        "✅ <b>Plan Updated Successfully</b>\n\n"
        f"📂 <b>Category:</b> {settings['categories'][cat]['name']}\n"
        f"📦 <b>Plan:</b> {plan['label']}\n"
        f"✏️ <b>Field:</b> {field}\n"
        f"🔁 <b>From:</b> {old_value}\n"
        f"➡️ <b>To:</b> {new_value}",
        parse_mode="HTML"
    )

    # 🔙 Show Edit Plan list again (ONE STEP BACK UI)
    plans = settings["categories"][cat].get("plans", {})
    kb = InlineKeyboardBuilder()

    for pid2, p in plans.items():
        kb.button(
            text=f"{p['label']} – {p['price']}",
            callback_data=f"editplan_{pid2}"
        )

    kb.button(text="⬅️ Back", callback_data="admin_cat_back")
    kb.adjust(1)

    await m.answer(
        "✏️ <b>Select another plan to edit</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

#delete plan

@dp.callback_query(F.data == "admin_delete_plan")
async def admin_delete_plan(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]

    settings = await get_settings()
    plans = settings["categories"][cat].get("plans", {})

    kb = InlineKeyboardBuilder()
    for pid, plan in plans.items():
        kb.button(
            text=f"🗑 {plan['label']} – {plan['price']}",
            callback_data=f"delplan_{pid}"
        )

    kb.button(text="⬅️ Back", callback_data="admin_cat_back")
    kb.adjust(1)

    await c.message.edit_text(
        "🗑 *Select plan to delete*",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("delplan_"))
async def confirm_delete_plan(c: types.CallbackQuery, state: FSMContext):
    pid = c.data.split("_", 1)[1]
    await state.update_data(delete_plan_id=pid)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_delete_plan")],
        [InlineKeyboardButton(text="✅ Confirm Delete", callback_data="confirm_delete_plan")]
    ])

    await c.message.edit_text(
        "⚠️ *Are you sure you want to delete this plan?*",
        parse_mode="Markdown",
        reply_markup=kb
    )
@dp.callback_query(F.data == "confirm_delete_plan")
async def delete_plan_final(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]
    pid = data["delete_plan_id"]

    await settings_col.update_one(
        {"_id": "main"},
        {"$unset": {f"categories.{cat}.plans.{pid}": ""}}
    )

    await c.answer("Deleted")
    await c.message.edit_text("🗑 Plan deleted successfully")

@dp.callback_query(F.data == "admin_cat_back")
async def admin_cat_back(c: types.CallbackQuery):
    await c.answer()
    await admin_cat_actions(c, FSMContext)
    
#set channel 

@dp.callback_query(F.data == "admin_set_channel")
async def admin_set_channel(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserState.set_channel_id)
    await c.message.edit_text("Send *CHANNEL ID* (example: -100123456789)", parse_mode="Markdown")

@dp.message(UserState.set_channel_id)
async def admin_save_channel(m: types.Message, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]

    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{cat}.channel_id": int(m.text)}}
    )

    await state.clear()
    await m.answer("✅ Channel ID saved")

@dp.callback_query(F.data == "admin_set_group")
async def admin_set_group(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserState.set_group_id)
    await c.message.edit_text("Send *GROUP ID* (example: -100987654321)", parse_mode="Markdown")

@dp.message(UserState.set_group_id)
async def admin_save_group(m: types.Message, state: FSMContext):
    data = await state.get_data()
    cat = data["admin_category"]

    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{cat}.group_id": int(m.text)}}
    )

    await state.clear()
    await m.answer("✅ Group ID saved")


#view category #
@dp.message(F.text == "📋 View Categories")
async def view_categories(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    s = await get_settings()
    text = "📋 *Categories*\n\n"

    for k, v in s["categories"].items():
        text += (
            f"🔑 `{k}`\n"
            f"📛 {v['name']}\n"
            f"💰 {v['price']}\n"
            f"🔗 {v['link']}\n\n"
        )

    await m.answer(text, parse_mode="Markdown")

@dp.message(F.text == "➕ Add Category")
async def add_cat_start(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    await state.set_state(UserState.add_cat_key)
    await m.answer("Enter *category key* (example: movie)", parse_mode="Markdown")

@dp.message(UserState.add_cat_key)
async def add_cat_key(m: types.Message, state: FSMContext):
    await state.update_data(key=m.text.lower())
    await state.set_state(UserState.add_cat_name)
    await m.answer("Enter *category name*", parse_mode="Markdown")

@dp.message(UserState.add_cat_name)
async def add_cat_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(UserState.add_cat_price)
    await m.answer("Enter *price* (example: 50 INR)", parse_mode="Markdown")

@dp.message(UserState.add_cat_price)
async def add_cat_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text)
    await state.set_state(UserState.add_cat_link)
    await m.answer("Enter *channel link*", parse_mode="Markdown")

@dp.message(UserState.add_cat_link)
async def add_cat_link(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {
            f"categories.{data['key']}": {
                "name": data["name"],
                "price": data["price"],
                "link": m.text
            }
        }}
    )

    await m.answer("✅ Category added successfully")

@dp.message(F.text == "✏️ Edit Category")
async def edit_cat_start(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    await state.set_state(UserState.edit_cat_select)
    await m.answer("Enter *category key* to edit", parse_mode="Markdown")

@dp.message(UserState.edit_cat_select)
async def edit_cat_field(m: types.Message, state: FSMContext):
    await state.update_data(key=m.text.lower())
    await state.set_state(UserState.edit_cat_field)
    await m.answer("What to edit? (`name` / `price` / `link`)", parse_mode="Markdown")

@dp.message(UserState.edit_cat_field)
async def edit_cat_value(m: types.Message, state: FSMContext):
    await state.update_data(field=m.text)
    await state.set_state(UserState.edit_cat_value)
    await m.answer("Enter new value", parse_mode="Markdown")

@dp.message(UserState.edit_cat_value)
async def save_edit(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{data['key']}.{data['field']}": m.text}}
    )

    await m.answer("✅ Category updated")


@dp.message(F.text == "🗑 Delete Category")
async def delete_cat_start(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    await state.set_state(UserState.delete_cat)
    await m.answer("Enter *category key* to delete", parse_mode="Markdown")

@dp.message(UserState.delete_cat)
async def delete_cat(m: types.Message, state: FSMContext):
    await state.clear()

    await settings_col.update_one(
        {"_id": "main"},
        {"$unset": {f"categories.{m.text.lower()}": ""}}
    )

    await m.answer("🗑 Category deleted")


@dp.message(Command("msg"))
async def admin_msg(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return

    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Usage:\n/msg user_id|@username message")

    target, text = parts[1], parts[2]

    if target.startswith("@"):
        user = await users_col.find_one({"username": target[1:]})
        if not user:
            return await m.answer("❌ User not found")
        uid = user["user_id"]
    else:
        uid = int(target)

    await bot.send_message(uid, f"💬 *Admin Message:*\n\n{text}", parse_mode="Markdown")
    await m.answer("✅ Message sent")


# ================= ADMIN COMMANDS =================
@dp.message(Command("setprice"))
async def set_price(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    _, cat, price = m.text.split(maxsplit=2)
    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{cat}.price": price}}
    )
    await m.answer("✅ Price updated")

@dp.message(Command("setlink"))
async def set_link(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    _, cat, link = m.text.split(maxsplit=2)
    await settings_col.update_one(
        {"_id": "main"},
        {"$set": {f"categories.{cat}.link": link}}
    )
    await m.answer("✅ Link updated")
# ===== background subscription===========

from datetime import datetime, timedelta

async def subscription_watcher():
    while True:
        now = datetime.utcnow()

        async for sub in subs_col.find({"status": "active"}):
            uid = sub["user_id"]
            expires_at = sub["expires_at"]
            remaining = (expires_at - now).days

            settings = await get_settings()
            cat = settings["categories"].get(sub["category"])

            # 🔔 REMINDER (2 or 1 days before)
            if remaining in (1, 2) and not sub.get("reminder_sent"):
                try:
                    await bot.send_message(
                        uid,
                        f"⏰ *VIP Expiry Reminder*\n\n"
                        f"Your VIP will expire in *{remaining} day(s)*.\n"
                        f"Renew to continue access 🔄",
                        parse_mode="Markdown"
                    )
                    await subs_col.update_one(
                        {"_id": sub["_id"]},
                        {"$set": {"reminder_sent": True}}
                    )
                except:
                    pass

            # ❌ EXPIRED
            if remaining < 0:
                try:
                    # Remove from channel
                    if cat.get("channel_id"):
                        await bot.ban_chat_member(cat["channel_id"], uid)
                        await bot.unban_chat_member(cat["channel_id"], uid)

                    # Remove from group
                    if cat.get("group_id"):
                        await bot.ban_chat_member(cat["group_id"], uid)
                        await bot.unban_chat_member(cat["group_id"], uid)

                    await bot.send_message(
                        uid,
                        "❌ *Your VIP has expired*\n\n"
                        "You have been removed from the VIP access.\n"
                        "Renew anytime to regain access 💎",
                        parse_mode="Markdown"
                    )
                except:
                    pass

                await subs_col.update_one(
                    {"_id": sub["_id"]},
                    {"$set": {"status": "expired"}}
                )

        # ⏳ Check every 10 minutes
        await asyncio.sleep(600)


# ================= MAIN =================
async def main():
    await start_web()
    await bot.delete_webhook(drop_pending_updates=True)

    # 🔥 START AUTO EXPIRY TASK
    asyncio.create_task(subscription_watcher())

    await dp.start_polling(bot)
    
if __name__ == "__main__":
    asyncio.run(main())
