# Use lightweight Python 3.9 Alpine image
FROM python:3.9-alpine

# Set working directory
WORKDIR /app

# Copy application files
COPY ./app /app

# Install dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && mkdir -p /app/logs

# Copy and make run script executable
COPY run.sh /
RUN chmod +x /run.sh

# Set entrypoint
CMD ["/run.sh"]
