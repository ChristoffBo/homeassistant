ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set shell options
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set working directory
WORKDIR /app

# Install required packages (adjust if needed)
RUN apk add --no-cache python3 py3-pip curl git

# Copy all local files
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Copy frontend files
COPY www/ /www/

# Optional: Copy any backend or API scripts
COPY uploader.py /app/uploader.py
COPY app/ /app/

# Expose web UI port (optional if Ingress is used)
EXPOSE 8080

# Default startup script
CMD [ "/run.sh" ]