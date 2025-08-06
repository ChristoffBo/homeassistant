FROM python:3.9-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install flask gitpython

# Set working directory
WORKDIR /app

# Copy add-on files
COPY app/ /app/

# Run the Flask server
CMD ["python", "app.py"]
