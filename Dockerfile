# Use stable Python (aiogram + motor friendly)
FROM python:3.11-slim

# Environment variables (VERY IMPORTANT for logs)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# System dependencies (needed for pillow & qrcode sometimes)
RUN apt-get update && apt-get install -y \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker cache optimization)
COPY requirements.txt .

# Upgrade pip + install deps
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port (Render uses it automatically)
EXPOSE 8080

# Start bot
CMD ["python", "bot.py"]
