FROM python:3.9-alpine

WORKDIR /app
COPY ./app /app

RUN pip install --no-cache-dir -r requirements.txt \
    && apk add --no-cache gcc musl-dev \
    && mkdir -p /app/logs

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]