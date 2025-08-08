ARG BUILD_FROM=debian:bullseye-slim
FROM ${BUILD_FROM}

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
      jq \
      python3 \
      python3-pip \
      skopeo \
      curl \
      ca-certificates \
      git \
      dumb-init && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Flask for backend API
RUN pip3 install flask

# Add registry binary (copied from official registry container)
ADD https://github.com/distribution/distribution/releases/download/v2.8.2/registry_2.8.2_linux_amd64.tar.gz /tmp/registry.tar.gz
RUN mkdir -p /registry && tar -xzf /tmp/registry.tar.gz -C /registry && chmod +x /registry/registry

# Copy add-on files
COPY run.sh /run.sh
COPY app /app
COPY www /www

# Expose ports
EXPOSE 8080 5000

# Entrypoint
ENTRYPOINT ["/bin/bash", "/run.sh"]