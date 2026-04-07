FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system-level dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data config

# Avoid buffered output so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Entry point:
# - Default to daemon for local Docker
# - Railway can override start command to: uvicorn railway_app:app --host 0.0.0.0 --port $PORT
CMD ["python", "daemon.py"]
