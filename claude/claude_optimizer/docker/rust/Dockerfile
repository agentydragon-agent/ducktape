FROM claude-base:latest

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install common Rust tools
RUN cargo install cargo-watch cargo-edit cargo-audit

# Install system dependencies for common Rust crates
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

LABEL dev.environment="rust"
LABEL dev.description="Rust development environment with cargo tools"