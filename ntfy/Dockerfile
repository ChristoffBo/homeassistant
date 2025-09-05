ARG BUILD_FROM=binwiederhier/ntfy:latest
FROM ${BUILD_FROM}

# Add tools to parse options and run entrypoint
RUN apk add --no-cache bash jq

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

EXPOSE 8008
CMD ["/usr/local/bin/run.sh"]
