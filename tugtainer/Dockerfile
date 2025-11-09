ARG BUILD_FROM
FROM ${BUILD_FROM}

# Copy run script
COPY run /

# Make run script executable
RUN chmod a+x /run

# Labels
LABEL \
    io.hass.name="Tugtainer" \
    io.hass.description="Docker container update automation with web UI" \
    io.hass.type="addon" \
    io.hass.version="v1.7.0"
