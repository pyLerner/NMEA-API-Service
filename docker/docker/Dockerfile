#FROM python:3.12-slim
FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1

# curl net-tools procps  may be added for debug
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    bash \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------- Python FastAPI ----------
COPY NavAPIServer/bin /app/NavAPIServer/bin
RUN chmod +x /app/NavAPIServer/bin/naviapiserv.bin

# ---------- Go binary ----------
COPY NDTPClient/bin /app/NDTPClient/bin
RUN chmod +x /app/NDTPClient/bin/NDTP_Client

# ---------- Entrypoint ----------
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data"]

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

