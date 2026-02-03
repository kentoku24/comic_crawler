FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    xvfb fluxbox \
    x11vnc \
    novnc websockify \
    supervisor \
    fonts-noto-cjk fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Chromium (arm64 supported - Google Chrome not available for Linux arm64)
RUN apt-get update \
  && apt-get install -y --no-install-recommends chromium \
  && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash chrome \
  && mkdir -p /data/chrome \
  && chown -R chrome:chrome /data

ENV DISPLAY=:0 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    SCREEN_W=1365 \
    SCREEN_H=768 \
    SCREEN_D=24

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY start-chrome.sh /usr/local/bin/start-chrome.sh
RUN chmod +x /usr/local/bin/start-chrome.sh

EXPOSE 6080 5900

# noVNC web root on Debian is /usr/share/novnc
CMD ["/usr/bin/supervisord", "-n"]
