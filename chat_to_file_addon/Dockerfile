FROM python:3.9-alpine

# Install system dependencies
RUN apk add --no-cache jq bash gcc musl-dev

WORKDIR /app
COPY ./app /app

# Install Python dependencies with version pinning
RUN pip install --no-cache-dir \
    flask==2.1.3 \
    werkzeug==2.1.2 \
    requests==2.28.1

# Create directories and set permissions
RUN mkdir -p /app/logs /share/chat_to_file \
    && chmod -R 777 /share/chat_to_file

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]