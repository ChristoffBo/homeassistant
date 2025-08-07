ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:latest
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

RUN apt-get update &&     apt-get install -y python3-pip &&     pip3 install apprise &&     pip3 install apprise-api &&     apt-get clean && rm -rf /var/lib/apt/lists/*

COPY rootfs/ /

RUN chmod +x /etc/cont-init.d/run.sh
