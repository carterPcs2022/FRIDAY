FROM python:3.11-slim

WORKDIR /app

# curl is required for the Docker healthcheck in docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p memory

# Matches docker-compose.yml, which sets PORT=8000 for the friday service
EXPOSE 8000

CMD ["python", "server.py"]
