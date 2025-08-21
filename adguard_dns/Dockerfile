# Base image is injected from build.json (official AdGuardHome)
ARG BUILD_FROM
FROM $BUILD_FROM

# Copy our startup script into the container
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Ensure run.sh is used as the entrypoint
CMD [ "/run.sh" ]
