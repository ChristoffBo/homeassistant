ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=1

# Best-effort apt update/upgrade at build time (won't fail if offline)
RUN (apt-get update || true) && (apt-get -y upgrade || true) &&     apt-get install -y --no-install-recommends python3 python3-pip curl ca-certificates jq &&     pip3 install --no-cache-dir flask requests waitress dnspython &&     apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server.py /app/server.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
COPY www /app/www

EXPOSE 8067
CMD ["/run.sh"]
