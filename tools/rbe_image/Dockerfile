# BuildBuddy RBE worker image with Docker support.
#
# Provides system tools needed by Bazel remote actions: python3 (for py_binary
# shebang bootstrap), build-essential (C linker for Rust toolchain bootstrap),
# git, ca-certificates, file/zip (for Bazel test-setup.sh), libtinfo5 (for
# GHC toolchain), Docker for container-based tests (Firecracker init-dockerd),
# and Chromium shared libraries for visual regression tests (headless_shell
# from rules_playwright).
FROM docker.io/library/ubuntu:24.04

# Enable universe repo and install dependencies.
RUN sed -i 's/^Components: main$/Components: main universe/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        docker.io \
        file \
        git \
        # iptables is a Recommends dep of docker.io, needed for dockerd networking
        iptables \
        libssl-dev \
        pkg-config \
        python3 \
        zip \
        # Chromium headless shell shared library dependencies
        libasound2t64 \
        libatk-bridge2.0-0t64 \
        libatk1.0-0t64 \
        libcups2t64 \
        libdrm2 \
        libgbm1 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libxcomposite1 \
        libxdamage1 \
        libxkbcommon0 \
        libxrandr2 \
        libxfixes3 \
        libxshmfence1 \
    && rm -rf /var/lib/apt/lists/* \
    # libtinfo5: dropped from noble (24.04), fetch from jammy (22.04) archive.
    # GHC 9.0.2 bindist requires libtinfo.so.5 for ghc-pkg during toolchain setup.
    && curl -fsSL -o /tmp/libtinfo5.deb \
        http://security.ubuntu.com/ubuntu/pool/universe/n/ncurses/libtinfo5_6.3-2ubuntu0.1_amd64.deb \
    && dpkg -i /tmp/libtinfo5.deb \
    && rm /tmp/libtinfo5.deb
