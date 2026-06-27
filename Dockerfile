FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
CMD ["gunicorn", "loom.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
