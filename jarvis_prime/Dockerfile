FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy runtime and modules
COPY run.sh /run.sh
COPY bot.py /app/bot.py
# Reuse the same modules style as Jnr; ARR & Weather & Chat are compatible:
COPY arr.py /app/arr.py
COPY weather.py /app/weather.py
COPY chat.py /app/chat.py
# Prime modules:
COPY uptimekuma.py /app/uptimekuma.py
COPY digest.py /app/digest.py

RUN chmod +x /run.sh

CMD [ "/run.sh" ]
