ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Create virtual environment first
RUN apk add --no-cache python3 && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip

WORKDIR /app

# Install requirements in venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app /app
COPY run.sh /

# Correct permissions for s6
RUN chmod a+x /run.sh && \
    chmod -R a+x /app

# s6-overlay compatible init
ENTRYPOINT ["/init"]
CMD ["/run.sh"]