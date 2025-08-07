FROM alpine:3.19

RUN apk add --no-cache curl su-exec tini

# Install ntfy
RUN curl -fsSL https://github.com/binwiederhier/ntfy/releases/latest/download/ntfy_0.12.0_linux_amd64.tar.gz \
    | tar -xz -C /usr/local/bin ntfy

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/run.sh"]
