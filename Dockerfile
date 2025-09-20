FROM php:8.2-fpm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    curl \
    git \
    supervisor \
    && apt-get clean

# Set up Python virtual environment and install Python packages
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install gallery-dl croniter yt-dlp

# Ensure shell and subprocess can find gallery-dl in virtualenv
ENV PATH="/opt/venv/bin:$PATH"

# Copy app source
COPY . /var/www/html/
RUN set -eux; \
    mkdir -p /downloads /logs /screenshots /tasks /config; \
    for dir in downloads logs screenshots tasks config; do \
        src="/var/www/html/$dir"; \
        dest="/$dir"; \
        if [ -d "$src" ] && [ -n "$(ls -A "$src" 2>/dev/null)" ]; then \
            cp -a "$src/." "$dest/"; \
        fi; \
        rm -rf "$src"; \
        ln -s "$dest" "$src"; \
    done; \
    chmod -R 777 /var/www/html /downloads /logs /screenshots /tasks /config
WORKDIR /var/www/html/

# Copy nginx and supervisor config
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf

# Expose HTTP
EXPOSE 80

# Start services
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]

