FROM python:3.10-slim

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
# System dependencies
# -----------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      git \
      curl \
      unzip \
      chromium \
      chromium-driver \
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
      dbus \
      xdg-utils \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# -----------------------------
# Install Bun (required by Camel MCP)
# -----------------------------
RUN curl -fsSL https://bun.sh/install | bash

# -----------------------------
# Copy backend code
# -----------------------------
COPY . .

# -----------------------------
# Install Python dependencies
# -----------------------------
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      fastapi uvicorn[standard] httpx aiofiles numpy debugpy \
      "camel-ai[eigent] @ git+https://github.com/szhengac/camel.git@gemini"

# -----------------------------
# Expose ports
# -----------------------------
EXPOSE 5002

# -----------------------------
# Copy entrypoint script
# -----------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# -----------------------------
# Use entrypoint
# -----------------------------
CMD ["/entrypoint.sh"]
