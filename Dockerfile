FROM python:3.11-slim

WORKDIR /app
ENV DB_PATH=/app/data/crochet_agent.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directory for SQLite persistence (mount a volume here on Railway)
RUN mkdir -p /app/data

EXPOSE 8080

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
