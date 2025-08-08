ARG BUILD_FROM=debian:bullseye-slim
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

RUN apt-get update && apt-get install -y \
    bash curl jq && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
