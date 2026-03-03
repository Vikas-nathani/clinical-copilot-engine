# ── Clinical Copilot Engine — Backend Dockerfile ────────────────────
# Multi-stage build for minimal production image.

# Stage 1: Builder — install dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Runtime — lean production image
FROM python:3.11-slim AS runtime

LABEL maintainer="Clinical Copilot Engine"
LABEL description="FastAPI backend for real-time clinical autocomplete"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Copy data directory (compiled data will be mounted or baked in)
# In production, mount data/compiled as a volume instead.

# Non-root user for security
RUN groupadd -r copilot && useradd -r -g copilot copilot
USER copilot

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); r.raise_for_status()" || exit 1

EXPOSE 8000

# Production: multi-worker Uvicorn
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--log-level", "info"]