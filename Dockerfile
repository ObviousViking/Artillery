FROM python:3.12-slim

# Install system deps: cron for scheduling, gosu for dropping privileges
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

# Volumes (Unraid will map these)
VOLUME ["/config", "/tasks", "/downloads"]

# Default envs; Unraid will override TASKS_DIR / CONFIG_DIR / DOWNLOADS_DIR
ENV FLASK_APP=app.py \
    DATA_DIR=/data

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:80", "app:app"]
