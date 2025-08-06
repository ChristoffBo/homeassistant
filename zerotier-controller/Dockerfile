ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install ZeroTier and Python
RUN apk add --no-cache zerotier-one python3 py3-pip bash curl

# Copy source files
COPY run.sh /run.sh
COPY app /app
COPY www /www

# Permissions
RUN chmod a+x /run.sh && \
    mkdir -p /var/lib/zerotier-one && \
    chown -R root:root /app /www

# Install Python backend dependencies
RUN pip3 install flask flask_cors

# Expose ports
EXPOSE 9993 8080

CMD [ "/run.sh" ]