# Use the official Zoraxy image as the base
FROM zoraxydocker/zoraxy:latest

# Add labels required by Home Assistant
LABEL \
    maintainer="cbothma <bothmacell@gmail.com>" \
    org.opencontainers.image.title="Zoraxy Home Assistant Add-on" \
    org.opencontainers.image.description="Zoraxy reverse proxy for Home Assistant" \
    org.opencontainers.image.source="https://github.com/yourusername/hassio-zoraxy" \
    org.opencontainers.image.licenses="MIT"

# Create necessary folders (optional, for future customization)
RUN mkdir -p /data /config

# Set workdir to config (optional)
WORKDIR /config

# Home Assistant requires all add-ons to define a run command
CMD ["./zoraxy"]
