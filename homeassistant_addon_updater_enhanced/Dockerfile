# syntax=docker/dockerfile:1.4
ARG BUILD_FROM
FROM $BUILD_FROM

# Install required dependencies
RUN apk add --no-cache bash jq curl

# Copy the main script
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Set entrypoint
ENTRYPOINT ["/run.sh"]
