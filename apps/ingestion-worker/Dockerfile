FROM python:3.12-slim

WORKDIR /app
COPY packages/trading-domain /packages/trading-domain
COPY apps/api /packages/goldie-api
COPY apps/ingestion-worker /app
RUN pip install --no-cache-dir /packages/trading-domain /packages/goldie-api .

CMD ["python", "-m", "goldie_ingestion_worker"]
