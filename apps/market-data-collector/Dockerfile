FROM python:3.12-slim

WORKDIR /app
COPY apps/market-data-collector /app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "goldie_collector"]
