FROM python:3.12-slim

WORKDIR /app

# System dependencies + serif fonts for the editorial collage style
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-unifont \
    wget \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libdrm2 \
    libgbm1 \
    libasound2t64 \
    libxshmfence1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Download Playfair Display — the luxury serif that matches Jackie Aina's editorial style.
# Falls back silently if network is unavailable; Liberation Serif is the fallback.
RUN mkdir -p /app/fonts && \
    wget -q "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/static/PlayfairDisplay-Black.ttf" \
        -O /app/fonts/PlayfairDisplay-Black.ttf || echo "Font download skipped (no network)" && \
    wget -q "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/static/PlayfairDisplay-Bold.ttf" \
        -O /app/fonts/PlayfairDisplay-Bold.ttf || true && \
    wget -q "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/static/PlayfairDisplay-Italic.ttf" \
        -O /app/fonts/PlayfairDisplay-Italic.ttf || true && \
    wget -q "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/static/PlayfairDisplay-Regular.ttf" \
        -O /app/fonts/PlayfairDisplay-Regular.ttf || true

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

# App code
COPY . .

# Temp dir for generated pin images
RUN mkdir -p /tmp/generated_images

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "300", "main:app"]
