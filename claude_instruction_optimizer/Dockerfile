# Multi-stage Dockerfile for coding agent with development tools
# Supports configurable base image via build arg

ARG BASE_IMAGE=gendosu/claude-code-docker:latest

# Generic repository base layer
FROM ${BASE_IMAGE} AS repo-base

ARG REPO_URL
ARG REPO_MOUNT_NAME  
ARG LOCAL_REPO_PATH

# Clone directly into final mount point
RUN mkdir -p /git/${REPO_MOUNT_NAME}
COPY ${LOCAL_REPO_PATH} /git/${REPO_MOUNT_NAME}/
WORKDIR /git/${REPO_MOUNT_NAME}

# Stage 1: System packages (rebuild rarely)
FROM ${BASE_IMAGE} AS system-base
USER root

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    mkdir -p /var/lib/apt/lists/partial && \
    chmod 755 /var/lib/apt/lists/partial && \
    apt-get update && apt-get install -y \
    bash \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    nodejs \
    npm \
    git \
    curl \
    wget \
    vim \
    nano \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    pkg-config \
    sqlite3 \
    jq \
    tree \
    htop \
    procps \
    net-tools \
    iputils-ping \
    telnet \
    zip \
    unzip \
    tar \
    gzip \
    libssl-dev \
    libpcap-dev \
    ruby-full \
    ruby-dev

# Stage 2: Rust runtime
FROM system-base AS rust

# Install Rust
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Stage 3: Go runtime
FROM system-base AS go

# Install Go
RUN --mount=type=cache,target=/tmp/go-download \
    cd /tmp/go-download && \
    wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"
ENV PATH="${GOPATH}/bin:${PATH}"

# Stage 4: Combined runtimes (for layers that need both)
FROM system-base AS runtimes

# Install Rust
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install Go
RUN --mount=type=cache,target=/tmp/go-download \
    cd /tmp/go-download && \
    wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"
ENV PATH="${GOPATH}/bin:${PATH}"

# Stage 5: Core Python dependencies (rebuild when core packages change)
FROM runtimes AS python-core

# Core Python packages (rarely change)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    requests \
    aiohttp \
    fastapi \
    uvicorn \
    flask \
    django \
    sqlalchemy

# Stage 6: Development tools (rebuild when dev tools change)
FROM python-core AS python-dev

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    pytest \
    black \
    flake8 \
    mypy \
    jupyter

# Stage 7: Data science packages (rebuild when data packages change)  
FROM python-dev AS python-data

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    pandas \
    numpy \
    matplotlib \
    seaborn

# Stage 8: Utility packages (rebuild when utilities change)
FROM python-data AS python-complete

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    click \
    typer \
    pydantic \
    httpx \
    asyncio \
    pydicom \
    opencv-python \
    pillow \
    scikit-image \
    beautifulsoup4 \
    lxml \
    pyhamcrest

# Stage 9: Node.js standalone
FROM system-base AS node

# Install Node.js packages
RUN --mount=type=cache,target=/root/.npm \
    npm install -g \
    typescript \
    prettier

# Stage 10: Ruby standalone  
FROM system-base AS ruby

# Install Ruby gems
RUN --mount=type=cache,target=/root/.gem \
    gem install bundler sqlite3 httparty colorize pry

# Stage 11: Node.js and Ruby combined packages
FROM python-complete AS packages-complete

# Install Node.js packages
RUN --mount=type=cache,target=/root/.npm \
    npm install -g \
    typescript \
    prettier

# Install Ruby gems
RUN --mount=type=cache,target=/root/.gem \
    gem install bundler sqlite3 httparty colorize pry

# Stage 12: Final environment setup
FROM packages-complete AS final

# Create workspace
RUN mkdir -p /workspace
WORKDIR /workspace

# Set shell and environment
SHELL ["/bin/bash", "-c"]
ENV PATH="/root/.cargo/bin:/usr/local/go/bin:/root/go/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
ENV PYTHONPATH="/workspace"
ENV GOPATH="/root/go"

# Switch to non-root user
USER 1000

# Keep original entrypoint
