ARG BUILD_FROM
FROM $BUILD_FROM

# Install required packages
RUN apk add --no-cache jq git curl python3 py3-pip
RUN pip3 install --no-cache-dir requests semver GitPython

# Set working directory
WORKDIR /app

# Copy the single script
COPY run.sh .

# Set execute permission
RUN chmod a+x run.sh

# Run the updater
CMD [ "./run.sh" ]
