# Base image is defined in build.json
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Add tools for option parsing
RUN apk add --no-cache jq bash

# Copy entry script
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

ENTRYPOINT ["/usr/local/bin/run.sh"]