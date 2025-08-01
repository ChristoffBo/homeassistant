ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Copy required files
COPY run.sh /
COPY app /app

# Install Python dependencies
RUN apk add --no-cache python3 py3-pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Set Python path
ENV PYTHONPATH=/app

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]