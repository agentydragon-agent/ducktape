# ActivityWatch server (aw-server-rust) with bundled web UI.
#
# Builds from source: Rust binary + aw-webui assets.
# Exposes port 5600 (REST API + web dashboard).
# Data stored in /data (mount a PVC here).
FROM rust:1.82-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git make npm \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --recurse-submodules --depth 1 \
    https://github.com/ActivityWatch/aw-server-rust.git .

# aw-webui needs npm deps + build, then cargo builds the Rust binary
# with the web assets embedded via include_dir!()
RUN make build

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -r -s /bin/false -m aw \
 && mkdir -p /data && chown aw:aw /data

COPY --from=builder /build/target/release/aw-server /usr/local/bin/aw-server

USER aw
EXPOSE 5600
VOLUME /data

ENTRYPOINT ["aw-server", "--host", "0.0.0.0", "--port", "5600", "--dbpath", "/data/db.sqlite3"]
