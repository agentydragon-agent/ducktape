FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    network-manager python3 \
    && rm -rf /var/lib/apt/lists/*
COPY sync.sh /sync.sh
COPY card.py /card.py
COPY sync.py /sync.py
RUN chmod +x /sync.sh
ENTRYPOINT ["/sync.sh"]
