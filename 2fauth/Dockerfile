ARG BUILD_FROM=ghcr.io/hassio-addons/base:13.2.1
FROM ${BUILD_FROM}

# Optional: install curl or tools you need
RUN apk add --no-cache curl

# Manually fetch and install 2FAuth (you'll need to adapt this part to fit 2FAuth setup)
# Or clone and build from source if necessary
# RUN curl -L https://example.com/2fauth.tar.gz | tar xz -C /app/

# Expose the port
EXPOSE 8001

# CMD to start the app (you must adapt this)
CMD ["/init"]
