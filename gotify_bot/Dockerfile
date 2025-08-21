FROM python:3.12-slim

RUN apt-get update -y && apt-get install -y --no-install-recommends \
      ca-certificates tzdata curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py /app/bot.py
COPY rules.yaml /app/rules.yaml
COPY run.sh /run.sh

RUN chmod +x /run.sh
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/run.sh"]