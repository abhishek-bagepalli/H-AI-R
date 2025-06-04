# Use official lightweight Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MEMORY_LIMIT=512M

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories
RUN mkdir -p documents db

# Expose port 8080 for Cloud Run
ENV PORT 8080

# Start Gunicorn server with optimized settings
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--timeout", "0", "--max-requests", "1000", "--max-requests-jitter", "50", "-b", "0.0.0.0:8080", "app:app"]
