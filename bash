pip install python-dotenv
chmod +x init_project.sh
./init_project.sh
#!/bin/bash

# Define project name
PROJECT_NAME="telegram_vip_bot"

echo "🚀 Initializing Project: $PROJECT_NAME..."

# Create directory
mkdir -p $PROJECT_NAME
cd $PROJECT_NAME

# 1. Create requirements.txt
echo "📝 Creating requirements.txt..."
cat <<EOF > requirements.txt
aiogram==3.3.0
motor==3.3.2
qrcode==7.4.2
pillow==10.2.0
dnspython==2.6.1
EOF

# 2. Create Dockerfile
echo "🐳 Creating Dockerfile..."
cat <<EOF > Dockerfile
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
EOF

# 3. Create .dockerignore
echo "🙈 Creating .dockerignore..."
cat <<EOF > .dockerignore
pycache
venv/
.env
.git
EOF

# 4. Create README.md
echo "📄 Creating README.md..."
cat <<EOF > README.md
# Telegram VIP Bot
A Telegram bot to accept UPI/PayPal payments and auto-invite users to VIP channels.

## Deployment on Render
1. Fork/Clone this repo.
2. Create a new Background Worker on Render.
3. Add Environment Variables:
   - \BOT_TOKEN\
   - \MONGO_URL\
   - \ADMIN_ID\
EOF

# 5. Create the Python Bot Code
echo "🐍 Creating bot.py..."
cat <<EOF > bot.py
import logging
import io
import asyncio
import os
import qrcode
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient

# Load Config
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    print("Error: ADMIN_ID not set or invalid.")
    ADMIN_ID = 0

# Database
cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["VipBotDB"]
settings_col = db["settings"]
users_col = db["users"]

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

class AdminState(StatesGroup):
    waiting_for_upi = State()
    waiting_for_link = State()

class UserState(StatesGroup):
    waiting_for_proof = State()

async def get_settings():
    settings = await settings_col.find_one({"_id": "main_settings"})
    if not settings:
        settings = {
            "_id": "main_settings",
            "upi_id": "example@upi",
            "paypal_link": "paypal.me/example",
            "price": "100 INR",
            "vip_link": "https://t.me/"
        }
        await settings_col.insert_one(settings)
    return settings

def generate_upi_qr(upi_id):
    upi_url = f"upi://pay?pa={upi_id}&pn=VIP_Payment&cu=INR"
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    kb = [[types.KeyboardButton(text="💎 Buy VIP Membership")]]
    await message.answer(
        "Welcome! Tap below to buy VIP access.", 
        reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    )

@dp.message(F.text == "💎 Buy VIP Membership")
async def buy_vip(message: types.Message):
    settings = await get_settings()
    price = settings.get('price')
    kb = [[types.InlineKeyboardButton(text="Pay via UPI", callback_data="pay_upi")]]
    await message.answer(f"Price: {price}\nSelect method:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "pay_upi")
async def pay_upi(callback: types.CallbackQuery, state: FSMContext):
    settings = await get_settings()
    qr = generate_upi_qr(settings.get('upi_id'))

Intel bills, [1/13/2026 11:31 PM]
await callback.message.answer_photo(
        photo=types.BufferedInputFile(qr.read(), filename="qr.png"),
        caption=f"Scan to pay to {settings.get('upi_id')}. Send screenshot below."
    )
    await state.set_state(UserState.waiting_for_proof)
    await callback.answer()

@dp.message(UserState.waiting_for_proof)
async def proof_handler(message: types.Message, state: FSMContext):
    kb = [[
        types.InlineKeyboardButton(text="Approve", callback_data=f"app_{message.from_user.id}"),
        types.InlineKeyboardButton(text="Reject", callback_data=f"rej_{message.from_user.id}")
    ]]
    await bot.send_message(ADMIN_ID, f"New Proof from {message.from_user.id}", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id)
    await message.answer("Proof sent to admin. Wait for approval.")
    await state.clear()

@dp.callback_query(F.data.startswith("app_"))
async def approve(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    settings = await get_settings()
    await bot.send_message(user_id, f"Approved! Join here: {settings.get('vip_link')}")
    await callback.message.edit_caption(caption="✅ Approved")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        kb = [[types.InlineKeyboardButton(text="Set UPI", callback_data="set_upi")]]
        await message.answer("Admin Panel", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "set_upi")
async def set_upi(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send new UPI ID")
    await state.set_state(AdminState.waiting_for_upi)

@dp.message(AdminState.waiting_for_upi)
async def save_upi(message: types.Message, state: FSMContext):
    await settings_col.update_one({"_id": "main_settings"}, {"\$set": {"upi_id": message.text}})
    await message.answer("Saved.")
    await state.clear()

async def main():
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())
EOF

# 6. Initialize Git
echo "🔧 Initializing Git..."
git init
git add .
git commit -m "Initial commit for VIP Bot"

echo "✅ Done! Project created in '$PROJECT_NAME' folder."
echo "👉 Next steps:"
echo "   1. cd $PROJECT_NAME"
echo "   2. Create a repo on GitHub."
echo "   3. git remote add origin <YOUR_GITHUB_URL>"
echo "   4. git push -u origin master"
EOF
