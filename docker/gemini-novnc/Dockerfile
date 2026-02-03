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

# Install Google Chrome (arm64 supported)
RUN install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
  && chmod a+r /etc/apt/keyrings/google-chrome.gpg \
  && echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends google-chrome-stable \
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
