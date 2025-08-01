ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    nginx

# Copy files
COPY rootfs /

# Set up Python
RUN pip install --no-cache-dir flask gunicorn

# Configure nginx for ingress
RUN rm /etc/nginx/http.d/default.conf
COPY nginx.conf /etc/nginx/http.d/ingress.conf

# Start script
CMD [ "/init" ]