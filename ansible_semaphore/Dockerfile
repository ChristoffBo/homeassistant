# Home Assistant add-on Dockerfile for Ansible Semaphore
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install requirements
RUN apk add --no-cache bash jq curl ca-certificates

# Semaphore version
ARG SEMAPHORE_VERSION=v2.16.17

# Download Semaphore binary
RUN curl -L -o /usr/local/bin/semaphore \
    https://github.com/semaphoreui/semaphore/releases/download/${SEMAPHORE_VERSION}/semaphore_linux_amd64 && \
    chmod +x /usr/local/bin/semaphore

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Set workdir
WORKDIR /share/ansible_semaphore

# Entrypoint
CMD [ "/run.sh" ]