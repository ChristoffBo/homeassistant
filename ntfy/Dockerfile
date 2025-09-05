ARG BUILD_FROM=binwiederhier/ntfy:latest
FROM ${BUILD_FROM}

# Add tools to parse options and run entrypoint; use apk if present else fallback to microdnf/apt (no-fail)
RUN (command -v apk >/dev/null && apk add --no-cache bash jq) ||     (command -v microdnf >/dev/null && microdnf install -y bash jq || true) ||     (command -v apt-get >/dev/null && apt-get update && apt-get install -y --no-install-recommends bash jq && rm -rf /var/lib/apt/lists/* || true) || true

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

EXPOSE 8008
CMD ["/usr/local/bin/run.sh"]
