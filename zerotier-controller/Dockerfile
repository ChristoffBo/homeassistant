FROM debian:bullseye-slim

LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

ENV LANG=C.UTF-8

# Install dependencies and ZeroTier
RUN apt-get update && \
    apt-get install -y \
        curl \
        gnupg \
        iproute2 \
        iptables \
        ca-certificates \
        nodejs \
        npm \
        git \
        jq \
        openssl \
        kmod \
        python3 \
    && curl -s https://install.zerotier.com | bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set up workdir
RUN mkdir -p /app
COPY . /app/
RUN chmod +x /app/run.sh /app/init.sh

EXPOSE 9993/udp
USER root
CMD ["/app/run.sh"]