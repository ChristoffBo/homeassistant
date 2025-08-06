ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

# Install necessary packages
RUN apk add --no-cache \
    bash \
    python3 \
    py3-pip \
    zerotier-one \
    tzdata \
    git

# Copy files
COPY run.sh /run.sh
COPY backend.py /app/backend.py
COPY www /www
RUN chmod +x /run.sh

CMD [ "/run.sh" ]