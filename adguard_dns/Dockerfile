# Base image is defined in build.json
ARG BUILD_FROM
FROM $BUILD_FROM

# Install tools required by run.sh
RUN apt-get update && \
    apt-get install -y jq curl && \
    rm -rf /var/lib/apt/lists/*

# Copy our startup script into the container
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Ensure run.sh is used as the entrypoint
CMD [ "/run.sh" ]
