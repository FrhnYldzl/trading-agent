FROM python:3.12-slim

WORKDIR /app

# Sistem bagimliliklari
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python bagimliliklari
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyalari
COPY server/ ./server/

# Port (Railway otomatik atar)
ENV PORT=8000
EXPOSE ${PORT}

# Baslat
WORKDIR /app/server
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
