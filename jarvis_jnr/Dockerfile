FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy bot and run script
COPY run.sh /run.sh
COPY bot.py /app/bot.py
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
