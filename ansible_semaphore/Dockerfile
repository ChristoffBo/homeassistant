ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache bash jq curl ca-certificates

ARG SEMAPHORE_VERSION=v2.16.17
RUN curl -L -o /usr/local/bin/semaphore \
    https://github.com/semaphoreui/semaphore/releases/download/${SEMAPHORE_VERSION}/semaphore_linux_amd64 && \
    chmod +x /usr/local/bin/semaphore

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]