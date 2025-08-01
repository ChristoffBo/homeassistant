ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

RUN apk add --no-cache python3 py3-pip git && \
    pip install --no-cache-dir flask requests PyGithub python-dotenv

COPY app /app
COPY run.sh /
COPY requirements.txt .

RUN chmod a+x /run.sh

CMD ["/run.sh"]
