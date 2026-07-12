FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System deps for Playwright (installed via --with-deps below)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Install Chromium + its OS dependencies
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "src.main"]
