# Multi-stage Dockerfile for coding agent with development tools
# Supports configurable base image via build arg

ARG BASE_IMAGE=gendosu/claude-code-docker:latest

# Generic repository base layer
FROM ${BASE_IMAGE} as repo-base

ARG REPO_URL
ARG REPO_MOUNT_NAME  
ARG LOCAL_REPO_PATH

# Clone directly into final mount point
RUN mkdir -p /git/${REPO_MOUNT_NAME}
COPY ${LOCAL_REPO_PATH} /git/${REPO_MOUNT_NAME}/
WORKDIR /git/${REPO_MOUNT_NAME}

# Stage 1: System packages (rebuild rarely)
FROM ${BASE_IMAGE} as system-base
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

# Stage 2: Language runtimes (rebuild when versions change)
FROM system-base as runtimes

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

# Stage 3: Core Python dependencies (rebuild when core packages change)
FROM runtimes as python-core

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

# Stage 4: Development tools (rebuild when dev tools change)
FROM python-core as python-dev

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    pytest \
    black \
    flake8 \
    mypy \
    jupyter

# Stage 5: Data science packages (rebuild when data packages change)  
FROM python-dev as python-data

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages \
    pandas \
    numpy \
    matplotlib \
    seaborn

# Stage 6: Utility packages (rebuild when utilities change)
FROM python-data as python-complete

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

# Stage 7: Node.js and Ruby packages
FROM python-complete as packages-complete

# Install Node.js packages
RUN --mount=type=cache,target=/root/.npm \
    npm install -g \
    typescript \
    prettier

# Install Ruby gems
RUN --mount=type=cache,target=/root/.gem \
    gem install bundler sqlite3 httparty colorize pry

# Stage 8: Final environment setup
FROM packages-complete as final

# Set up shell environment and workspace
RUN echo 'alias ll="ls -la"' >> /root/.bashrc && \
    echo 'alias la="ls -A"' >> /root/.bashrc && \
    echo 'alias l="ls -CF"' >> /root/.bashrc && \
    echo 'export PS1="\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "' >> /root/.bashrc

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