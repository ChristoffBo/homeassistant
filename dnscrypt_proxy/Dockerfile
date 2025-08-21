# Stage 1: pull dnscrypt-proxy from klutchell image
FROM klutchell/dnscrypt-proxy:latest AS src

# Stage 2: runnable image with shell and tools
FROM alpine:3.20

RUN apk add --no-cache ca-certificates jq bash

# Copy the dnscrypt-proxy binary from the klutchell stage
COPY --from=src /usr/local/bin/dnscrypt-proxy /usr/local/bin/dnscrypt-proxy

# Add entry script that renders config from HA options
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh /usr/local/bin/dnscrypt-proxy

ENTRYPOINT ["/usr/local/bin/run.sh"]