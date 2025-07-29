FROM gitea/gitea:1.18.0

# Configure environment
RUN mkdir -p /data/gitea && \
    adduser -D -h /data/gitea -s /bin/bash git && \
    chown -R git:git /data/gitea

# Copy entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Persistence
VOLUME ["/data/gitea"]

# Ports
EXPOSE 3000 2222

# Startup
ENTRYPOINT ["/run.sh"]