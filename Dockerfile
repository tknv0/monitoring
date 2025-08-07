FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Nixtla SDK and prometheus_client
RUN pip install nixtla==0.6.6 prometheus_client==0.20.0 pandas==2.2.2 requests==2.32.3

# Set working directory
WORKDIR /app

# Copy analysis script
COPY analyze_metrics.py /app/analyze_metrics.py

# Expose port for Prometheus metrics
EXPOSE 8001

# Run the analysis script
CMD ["python", "/app/analyze_metrics.py"]