# Build context must be the parent directory containing both `Horizon/` and `smart_money/`.
# `docker-compose.yml` sets context: .. for this reason.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_DEBUG=0 \
    PORT=5001 \
    SMART_MONEY_DIR=/app/smart_money \
    SMART_MONEY_DB_PATH=/app/data/smart_money.db \
    HORIZON_DB_PATH=/app/data/horizon.db

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Horizon deps
COPY Horizon/requirements.txt /tmp/horizon-requirements.txt
RUN pip install -r /tmp/horizon-requirements.txt

# Install smart_money deps
COPY smart_money/requirements.txt /tmp/sm-requirements.txt
RUN pip install -r /tmp/sm-requirements.txt

# Copy smart_money project (ETL + CLI)
COPY smart_money/ /app/smart_money/

# Copy Horizon
COPY Horizon/ /app/horizon/

WORKDIR /app/horizon

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5001/ || exit 1

CMD ["python", "app.py"]
