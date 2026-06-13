FROM python:3.12-slim

WORKDIR /app
COPY packages/trading-domain /packages/trading-domain
COPY apps/api /app
RUN pip install --no-cache-dir /packages/trading-domain .

CMD ["sh", "-c", "alembic upgrade head && uvicorn goldie_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
