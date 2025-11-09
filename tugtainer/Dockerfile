ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set working directory
WORKDIR /tugtainer

# Ensure persistent storage directory exists
RUN mkdir -p /tugtainer

# Labels
LABEL \
    io.hass.name="Tugtainer" \
    io.hass.description="Docker container update automation with web UI" \
    io.hass.type="addon" \
    io.hass.version="1.0.0"
