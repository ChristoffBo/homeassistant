FROM python:3.9-alpine

# Install dependencies
RUN apk add --no-cache jq gcc musl-dev

WORKDIR /app
COPY ./app /app

# Pin Werkzeug to compatible version (fixes url_quote error)
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/logs

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]