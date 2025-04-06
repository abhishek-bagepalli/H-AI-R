# Use an official lightweight Python image
FROM python:3.10-slim

# Set working directory in container
WORKDIR /app

# Copy all files from local project to container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables (optional, you can also use Cloud Run's env settings)
ENV PYTHONUNBUFFERED=1

# Expose port 8080 for Flask
EXPOSE 8080

# Start your Flask app
CMD ["python", "app.py"]
