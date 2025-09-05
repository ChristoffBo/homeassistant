ARG BUILD_FROM=binwiederhier/ntfy:latest
FROM ${BUILD_FROM}

# Add tools to parse options and run entrypoint; try multiple package managers
RUN (command -v apk >/dev/null && apk add --no-cache bash jq findutils) ||     (command -v microdnf >/dev/null && microdnf install -y bash jq findutils || true) ||     (command -v apt-get >/dev/null && apt-get update && apt-get install -y --no-install-recommends bash jq findutils && rm -rf /var/lib/apt/lists/* || true) || true

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

EXPOSE 8008
CMD ["/usr/local/bin/run.sh"]
