FROM python:3.10-slim

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# -----------------------------
# System dependencies
# -----------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      git \
      chromium \
      chromium-driver \
      fonts-liberation \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnss3 \
      libxcomposite1 \
      libxdamage1 \
      libxrandr2 \
      xdg-utils \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy backend source code into the image
COPY . .

# Install Python dependencies (mirrors backend/pyproject.toml)
# Use CAMEL from szhengac/camel gemini branch:
# https://github.com/szhengac/camel/tree/gemini
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      pip>=23.0 \
      "fastapi>=0.115.12" \
      "fastapi-babel>=1.0.0" \
      "uvicorn[standard]>=0.34.2" \
      "pydantic-i18n>=0.4.5" \
      "python-dotenv>=1.1.0" \
      "httpx[socks]>=0.28.1" \
      "pydash>=8.0.5" \
      "inflection>=0.5.1" \
      "aiofiles>=24.1.0" \
      "openai>=1.99.3,<2" \
      "nodejs-wheel>=22.18.0" \
      "numpy>=1.23.0,<2.0.0" \
      "debugpy>=1.8.17" \
      "opentelemetry-api>=1.34.1" \
      "opentelemetry-sdk>=1.34.1" \
      "opentelemetry-exporter-otlp-proto-http>=1.34.1" \
      "google-genai==1.60.0"

# Install CAMEL separately (GitHub dependency requires git in image)
RUN pip install --no-cache-dir \
      "camel-ai[eigent] @ git+https://github.com/szhengac/camel.git@gemini"

# Expose the FastAPI port
EXPOSE 5002

# -----------------------------
# Entrypoint: start Chromium + FastAPI
# -----------------------------
CMD chromium \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --disable-dev-shm-usage \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9222 & \
  uvicorn main:api --host 0.0.0.0 --port 5002

