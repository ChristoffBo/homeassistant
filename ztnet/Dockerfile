FROM alpine:latest

# Install dependencies
RUN apk add --no-cache bash curl git postgresql postgresql-client \
    nodejs npm zerotier-one supervisor

# Create necessary directories
RUN mkdir -p /app /data/zerotier-one /data/postgres /var/log/supervisor

# Clone ZTNet (controller UI)
RUN git clone https://github.com/sinamics/ztnet /app

# Install NodeJS dependencies for ZTNet
WORKDIR /app
RUN npm install

# Copy configs and entry script
COPY run.sh /run.sh
COPY supervisord.conf /etc/supervisord.conf
RUN chmod +x /run.sh

CMD ["/run.sh"]
