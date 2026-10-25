FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code: the entrypoint plus the farm_agent package it imports.
COPY app.py .
COPY farm_agent/ ./farm_agent/

# Writable directory for runtime files (e.g. a jsonl event store path set via
# WIRING_CONFIG), since the non-root user can't write to /app itself.
RUN useradd --system --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser /app/data
USER 10001

EXPOSE 8080

CMD ["python", "app.py"]
