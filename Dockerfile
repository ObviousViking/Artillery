FROM python:3.12-slim

# Install system deps: cron and gosu (now from Debian repos!)
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron gosu \
    && rm -rf /var/lib/apt/lists/*

# Rest unchanged...
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

VOLUME ["/config", "/tasks", "/downloads"]

ENV FLASK_APP=app.py \
    DATA_DIR=/data

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:80", "app:app"]