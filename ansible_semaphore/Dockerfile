ARG BUILD_FROM
FROM ${BUILD_FROM}

# Ensure we are root for setup steps
USER root

# Install minimal tools to read add-on options (jq, bash) across base distros
RUN if command -v apk >/dev/null 2>&1; then \
      apk add --no-cache jq bash; \
    elif command -v apt-get >/dev/null 2>&1; then \
      apt-get update && apt-get install -y --no-install-recommends jq bash && rm -rf /var/lib/apt/lists/*; \
    elif command -v microdnf >/dev/null 2>&1; then \
      microdnf install -y jq bash && microdnf clean all; \
    else \
      echo "WARN: could not detect package manager; assuming jq and bash exist"; \
    fi

# Add entrypoint
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

# Default command
CMD ["/usr/local/bin/run.sh"]