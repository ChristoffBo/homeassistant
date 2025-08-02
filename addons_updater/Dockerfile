ARG BUILD_FROM
FROM $BUILD_FROM

# Install required packages
RUN apk add --no-cache jq git curl python3 py3-pip
RUN pip3 install --no-cache-dir requests semver GitPython

# Copy the entire rootfs structure
COPY rootfs /

# Set execute permission for the script
RUN chmod a+x /usr/bin/addons_updater.sh

# Run the updater script
CMD [ "/usr/bin/addons_updater.sh" ]
