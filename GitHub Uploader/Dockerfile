ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.18
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

RUN apk add --no-cache python3 py3-pip git curl

WORKDIR /app

COPY uploader.py /app/
COPY options.json /data/options.json

EXPOSE 7860

CMD [ "python3", "/app/uploader.py" ]
