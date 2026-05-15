FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_DEBUG=0 \
    PORT=5001 \
    SMART_MONEY_DIR=/app/smart_money \
    SMART_MONEY_DB_PATH=/app/data/smart_money.db \
    HORIZON_DB_PATH=/app/data/horizon.db

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY . /app/

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5001/ || exit 1

CMD ["python", "app.py"]
