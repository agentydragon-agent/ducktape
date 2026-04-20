FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    wpasupplicant iproute2 isc-dhcp-client iw python3-pip \
    && pip3 install --break-system-packages ezshare \
    && rm -rf /var/lib/apt/lists/*
COPY sync.sh /sync.sh
ENTRYPOINT ["/sync.sh"]
