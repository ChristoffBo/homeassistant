ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Install Python and create virtual environment
RUN apk add --no-cache python3 py3-pip git && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip

# Install requirements in venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app /app
COPY run.sh /

# Set permissions
RUN chmod a+x /run.sh

ENTRYPOINT ["/init"]
CMD ["/run.sh"]