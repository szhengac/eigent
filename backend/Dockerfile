FROM ubuntu:22.04

# -----------------------------
# Environment variables
# -----------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHROME_HEADLESS=1 \
    CHROME_NO_SANDBOX=1 \
    CHROME_DISABLE_GPU=1 \
    CHROME_DISABLE_SOFTWARE_RASTERIZER=1 \
    PATH="/root/.bun/bin:$PATH"

WORKDIR /backend

# -----------------------------
# System dependencies including DBus
# -----------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3.10 python3-pip python3-venv \
      build-essential \
      git \
      curl \
      unzip \
      chromium \
      chromium-driver \
      dbus \
      fonts-liberation \
      fonts-dejavu-core \
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
      libx11-xcb1 \
      libxshmfence1 \
      libxrender1 \
      libxfixes3 \
      libxcursor1 \
      libxinerama1 \
      libpango-1.0-0 \
      libcairo2 \
      xdg-utils \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# -----------------------------
# Install Bun (for Camel MCP)
# -----------------------------
RUN curl -fsSL https://bun.sh/install | bash

# -----------------------------
# Copy backend code
# -----------------------------
COPY . .

# -----------------------------
# Python dependencies
# -----------------------------
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir \
      pip>=23.0 \
      fastapi>=0.115.12 \
      fastapi-babel>=1.0.0 \
      uvicorn[standard]>=0.34.2 \
      uvloop>=0.17.0 \
      pydantic-i18n>=0.4.5 \
      python-dotenv>=1.1.0 \
      httpx[socks]>=0.28.1 \
      pydash>=8.0.5 \
      inflection>=0.5.1 \
      aiofiles>=24.1.0 \
      openai>=1.99.3,<2 \
      nodejs-wheel>=22.18.0 \
      numpy>=1.23.0,<2.0.0 \
      debugpy>=1.8.17 \
      opentelemetry-api>=1.34.1 \
      opentelemetry-sdk>=1.34.1 \
      opentelemetry-exporter-otlp-proto-http>=1.34.1 \
      google-genai==1.60.0 && \
    pip3 install --no-cache-dir \
      "camel-ai[eigent] @ git+https://github.com/szhengac/camel.git@gemini"

# -----------------------------
# Expose FastAPI port only
# -----------------------------
EXPOSE 5002

# -----------------------------
# Entrypoint script
# -----------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
