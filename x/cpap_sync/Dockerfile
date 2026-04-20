FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    network-manager python3-pip \
    && pip3 install --break-system-packages ezshare \
    && rm -rf /var/lib/apt/lists/*
COPY sync.sh /sync.sh
ENTRYPOINT ["/sync.sh"]
