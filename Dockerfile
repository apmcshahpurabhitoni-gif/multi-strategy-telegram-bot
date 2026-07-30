FROM python:3.12-slim

WORKDIR /app

# Install build deps that yfinance / pandas sometimes need
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render free tier uses PORT env var (default 10000)
ENV PORT=10000
EXPOSE 10000

# Use gunicorn for the flask part + polling in a worker
CMD ["python", "main.py"]
