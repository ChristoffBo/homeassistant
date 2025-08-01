ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Copy required files
COPY run.sh /
COPY app /app

# Install Python in a venv to avoid PEP 668 issues
RUN apk add --no-cache python3 && \
    python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -r /app/requirements.txt

ENV PATH="/venv/bin:$PATH"
ENV PYTHONPATH=/app

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]