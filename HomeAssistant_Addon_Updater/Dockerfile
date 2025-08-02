ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest  
FROM ${BUILD_FROM}  

# Install core dependencies  
RUN apk add --no-cache \  
    bash \  
    curl \  
    git \  
    jq \  
    tzdata \  
    s6-overlay  

# Create directory structure  
RUN mkdir -p \  
    /etc/cont-init.d \  
    /etc/services.d/addon-updater \  
    /usr/bin \  
    /var/log  

# Copy root filesystem  
COPY rootfs/usr/bin/* /usr/bin/  
COPY rootfs/etc/cont-init.d/* /etc/cont-init.d/  
COPY rootfs/etc/services.d/addon-updater/run /etc/services.d/addon-updater/  

# Set permissions  
RUN chmod a+x \  
    /usr/bin/addon_updater \  
    /usr/bin/run.sh \  
    /etc/cont-init.d/addon-updater \  
    /etc/services.d/addon-updater/run && \  
    touch /var/log/addon-updater.log && \  
    chmod 644 /var/log/addon-updater.log  

# Health check  
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \  
    CMD pgrep -f addon_updater || exit 1  

WORKDIR /data  
ENTRYPOINT ["/init"]  
CMD []  
