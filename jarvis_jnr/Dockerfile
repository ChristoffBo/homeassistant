ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM $BUILD_FROM

# Install dependencies (Alpine package manager)
RUN apk add --no-cache \
    python3 py3-pip curl jq bashio

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy bot and run script
COPY run.sh /run.sh
COPY bot.py /app/bot.py
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
