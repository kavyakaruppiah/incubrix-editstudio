FROM python:3.11-slim

# Install system dependencies including ffmpeg and font utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create necessary directories
RUN mkdir -p data/storage data/renders data/temp

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD ["sh", "-c", "curl -f \"http://localhost:${PORT:-${APP_PORT:-8000}}/api/v1/health\" || exit 1"]

CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-${APP_PORT:-8000}}\""]
