# Home Assistant base image
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    build-base \
    python3-dev

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    gunicorn \
    python-dotenv

# Copy application files
COPY rootfs /

# Set working directory
WORKDIR /app

# Set environment variables
ENV FLASK_APP=main.py
ENV FLASK_ENV=production

# Run Gunicorn (WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "main:app"]