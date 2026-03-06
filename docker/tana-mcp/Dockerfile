FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99

# Electron / Chromium runtime deps, Xvfb, x11vnc, noVNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc novnc websockify \
    # Electron / Chromium shared libraries
    libgtk-3-0 libnotify4 libnss3 libxss1 libasound2t64 \
    libgbm1 libsecret-1-0 libatk-bridge2.0-0 libatk1.0-0 \
    libdrm2 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 \
    libpango-1.0-0 libcairo2 libcups2 libdbus-1-3 libexpat1 \
    libxkbcommon0 \
    # Misc
    dbus-x11 fonts-noto-core ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash tana \
 && mkdir -p /home/tana/.config/Tana \
 && chown -R tana:tana /home/tana

# Download and extract Tana Desktop from GitHub releases.
# The zip contains a directory with the Electron app.
ARG TANA_VERSION=1.513.10
RUN curl -fsSL \
      "https://github.com/tanainc/tana-desktop-releases/releases/download/v${TANA_VERSION}/Tana-linux-x64-${TANA_VERSION}.zip" \
      -o /tmp/tana.zip \
 && unzip -q /tmp/tana.zip -d /opt/tana \
 && rm /tmp/tana.zip \
 && chmod +x /opt/tana/Tana-linux-x64/Tana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER tana
WORKDIR /home/tana

# 8262 = Tana MCP server, 6080 = noVNC web UI
EXPOSE 8262 6080

ENTRYPOINT ["/entrypoint.sh"]
