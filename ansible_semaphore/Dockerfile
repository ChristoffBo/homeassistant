FROM semaphoreui/semaphore:latest

# Use a non-root user if needed (image already runs as root by default)
# Create /data directory for persistence
RUN mkdir -p /data && chown 1000:1000 /data

# Switch to non-root user (Semaphore image runs as root, but for HA safety)
USER root

# Copy the startup script into the image
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Switch to non-root environment if desired
# (Semaphore image handles permissions internally)
# USER semaphore (if exists)

WORKDIR /

# Use healthcheck if needed
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -fk http://localhost:10443/ || exit 1

# Expose the default port
EXPOSE 3000  # Internal image default

CMD ["/run.sh"]
