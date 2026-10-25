# Dev Dockerfile for the JalRekha FastAPI backend.
# Optimized for fast iteration with `docker compose up`, not for production size.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
# Install dependencies first (cache-friendly). Source is bind-mounted in dev.
RUN uv pip install --system -e .[dev] || pip install -e .[dev] || true

COPY . .

ENV PYTHONPATH=src
EXPOSE 8000

CMD ["uvicorn", "jalrekha.main:app", "--host", "0.0.0.0", "--port", "8000"]
