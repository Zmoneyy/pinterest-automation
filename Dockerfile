FROM python:3.12-slim

WORKDIR /app

# System dependencies + serif fonts for the editorial collage style
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-dejavu-core \
    wget \
    ca-certificates \
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
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Temp dir for generated pin images
RUN mkdir -p /tmp/generated_images

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "main:app"]
