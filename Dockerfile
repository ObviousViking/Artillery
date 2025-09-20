FROM php:8.2-fpm

# OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx python3 python3-pip python3-venv ffmpeg curl git supervisor gosu \
 && rm -rf /var/lib/apt/lists/*

# Python venv + tools
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install gallery-dl croniter yt-dlp
ENV PATH="/opt/venv/bin:$PATH"

# App
WORKDIR /var/www/html
COPY . /var/www/html

# Configs
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf

# Defaults (overridable in Unraid/Compose)
ENV PUID=1000 PGID=1000 UMASK=002 TZ=Europe/London

# Entrypoint fixes permissions and user mapping, then starts supervisord
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/supervisord","-c","/etc/supervisord.conf"]
