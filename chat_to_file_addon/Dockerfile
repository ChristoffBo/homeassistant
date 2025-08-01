FROM python:3.9-slim

# Install only essential dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ./app /app

# Install pinned versions that work together
RUN pip install --no-cache-dir \
    flask==2.0.3 \
    werkzeug==2.0.3 \
    requests==2.26.0

# Create directories with full permissions
RUN mkdir -p /app/logs /share/chat_to_file \
    && chmod -R 777 /share/chat_to_file

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]