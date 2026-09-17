FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system --gid 10001 appuser \
    && adduser --system --uid 10001 --ingroup appuser appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/storage /app/storage/uploads /app/storage/logbook_photos \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000

CMD gunicorn app:app --bind 0.0.0.0:${PORT:-10000}