# Dockerfile for coding agent with development tools
FROM gendosu/claude-code-docker:latest

# Switch to root user to install packages
USER root

# Fix apt permissions and install system packages and development tools
RUN mkdir -p /var/lib/apt/lists/partial && \
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
    ruby-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install Go
RUN wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz && \
    rm go1.21.6.linux-amd64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"
ENV PATH="${GOPATH}/bin:${PATH}"

# Install common Python packages (break system packages for Docker)
RUN pip3 install --no-cache-dir --break-system-packages \
    requests \
    aiohttp \
    fastapi \
    uvicorn \
    flask \
    django \
    sqlalchemy \
    pytest \
    black \
    flake8 \
    mypy \
    jupyter \
    pandas \
    numpy \
    matplotlib \
    seaborn \
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

# Install essential Node.js packages globally (reduced list for faster build)
RUN npm install -g \
    typescript \
    prettier

# Install Ruby gems
RUN gem install bundler sqlite3 httparty colorize pry

# Set up a more complete shell environment
RUN echo 'alias ll="ls -la"' >> /root/.bashrc && \
    echo 'alias la="ls -A"' >> /root/.bashrc && \
    echo 'alias l="ls -CF"' >> /root/.bashrc && \
    echo 'export PS1="\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "' >> /root/.bashrc

# Create a development workspace
RUN mkdir -p /workspace
WORKDIR /workspace

# Set the default shell to bash
SHELL ["/bin/bash", "-c"]

# Ensure proper permissions and executable paths
ENV PATH="/root/.cargo/bin:/usr/local/go/bin:/root/go/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
ENV PYTHONPATH="/workspace"
ENV GOPATH="/root/go"

# Switch to the existing non-root user (UID 1000) for security and to allow --dangerously-skip-permissions
USER 1000

# Keep the original entrypoint from the base image
# This should still run the Claude CLI when the container starts