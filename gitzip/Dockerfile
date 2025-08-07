ARG BUILD_FROM
FROM $BUILD_FROM

# Install dependencies
RUN apk add --no-cache python3 py3-pip git unzip nodejs npm

# Copy data for add-on
COPY run.sh /
COPY app /app

# Install Python dependencies
RUN pip3 install requests PyGithub

# Install Node.js dependencies
WORKDIR /app
RUN npm install

# Make run script executable
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
