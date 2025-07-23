
FROM debian:bullseye-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
        curl \
        bash \
        supervisor \
        git \
        gnupg && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

RUN curl -s https://install.zerotier.com | bash

RUN mkdir -p /var/lib/zerotier-one /app/backend/data /var/log/supervisor

WORKDIR /opt

RUN git clone https://github.com/dec0dos/zero-ui.git

WORKDIR /opt/zero-ui

# Remove husky postinstall script BEFORE npm install
RUN npm pkg delete scripts.postinstall

# Install npm dependencies
RUN npm install --production --legacy-peer-deps

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 4000

CMD ["/usr/bin/supervisord"]