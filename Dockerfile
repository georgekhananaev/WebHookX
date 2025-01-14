# Use a lightweight Python base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements file
COPY requirements.txt /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . /app

# Expose port 51122 (for documentation—actual published port is set in docker-compose)
EXPOSE 51122

# Run the FastAPI app on 0.0.0.0:51122
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "51122"]
