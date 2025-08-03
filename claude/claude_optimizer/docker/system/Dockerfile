FROM claude-base:latest

# Install system development tools for C/C++
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    gdb \
    valgrind \
    pkg-config \
    libpcap-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

LABEL dev.environment="system"
LABEL dev.description="System development environment for C/C++ with debugging tools"