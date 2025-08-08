FROM debian:bullseye-slim

# Install required tools
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    bash \
    skopeo \
    python3 \
    python3-pip \
    git \
    && apt-get clean

# Install registry binary
RUN curl -L https://github.com/distribution/distribution/releases/download/v2.8.2/registry_2.8.2_linux_amd64.tar.gz \
    | tar -xz -C /usr/bin --strip-components=1 registry

# Install Flask
RUN pip3 install flask

# Copy app files and www content
COPY run.sh /run.sh
COPY app /app
COPY www /www
COPY registry/config.yml /etc/docker/registry/config.yml

# Make sure scripts are executable
RUN chmod +x /run.sh

# Expose registry and UI ports
EXPOSE 5000 8080

CMD ["/run.sh"]
