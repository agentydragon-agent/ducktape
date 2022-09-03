# Latest as of 2022-07-11
FROM ubuntu:22.04

# Add Bazel source.
RUN apt update && apt install -y ca-certificates
ADD bazel.gpg /etc/apt/trusted.gpg.d/
RUN echo "deb [arch=amd64] https://storage.googleapis.com/bazel-apt stable jdk1.8" | tee /etc/apt/sources.list.d/bazel.list

# Install build dependencies and Bazel.
# pkg-config: needed to configure SSL. libssl-dev: native SSL
# libtinfo5, libgmp-dev: needed for Haskell
RUN apt update && \
  apt full-upgrade -y && \
  DEBIAN_FRONTEND=noninteractive apt install -y \
    bazel \
    git \
    python-is-python3 \
    python3-pip \
    pkg-config \
    libssl-dev \
    libtinfo5 \
    libgmp-dev \
    && \
  apt clean && \
  apt autoremove -y

# For Ansible
RUN pip3 install ansible ansible-lint
