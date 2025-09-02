FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    supervisor \
    ffmpeg \
    nginx \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Copy only requirements first (leverages Docker cache for faster builds)
COPY requirements.txt /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of your app
COPY . /app/

# Optional default environment variable
ENV INTERVAL=3600

EXPOSE 8000

COPY supervisord.conf /etc/supervisord.conf

COPY nginx.conf /etc/nginx/nginx.conf

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Entry point to run migrations and start Django server
CMD ["/app/entrypoint.sh"]
