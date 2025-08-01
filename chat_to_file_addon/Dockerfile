FROM python:3.9-slim

WORKDIR /app
COPY ./app /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /share/chat_to_file \
    && chmod 777 /share/chat_to_file

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]