FROM python:3.12-slim

# Install cron and gosu (latest version, no signature verification)
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron wget \
    && rm -rf /var/lib/apt/lists/* \
    && set -eux; \
    GOSU_VERSION=1.19; \
    dpkgArch="$(dpkg --print-architecture | awk -F- '{ print $NF }')"; \
    wget -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-${dpkgArch}"; \
    chmod +x /usr/local/bin/gosu; \
    gosu --version; \
    gosu nobody true  # Quick verification it works

# Rest of your Dockerfile stays the same
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