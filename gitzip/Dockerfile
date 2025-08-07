ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache python3 py3-pip git unzip nodejs npm

# Create and activate a virtual environment for Python packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies in the virtual environment
RUN pip3 install --no-cache-dir requests PyGithub

# Copy data for add-on
COPY run.sh /
COPY app /app

# Install Node.js dependencies
WORKDIR /app
RUN npm install

# Make run script executable
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
