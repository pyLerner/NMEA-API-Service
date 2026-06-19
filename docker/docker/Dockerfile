FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        tzdata \
    && ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime \
    && echo "Etc/UTC" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

RUN mkdir -p /app /bin /db /log /etc/navigator

COPY NavAPIServer/bin/naviapiserv.bin /bin/naviapiserv.bin
COPY NDTPClient/bin/NDTP_Client /bin/NDTP_Client
RUN chmod +x /bin/naviapiserv.bin /bin/NDTP_Client \
    && ln -sf NDTP_Client /bin/NDTPClient

COPY etc/ /etc/navigator/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]
