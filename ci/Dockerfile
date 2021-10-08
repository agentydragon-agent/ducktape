FROM ubuntu:latest

# Add Bazel source.
RUN apt update && \
  apt install -y \
    curl \
    gnupg2
RUN curl https://bazel.build/bazel-release.pub.gpg | apt-key add -
RUN echo "deb [arch=amd64] https://storage.googleapis.com/bazel-apt stable jdk1.8" > /etc/apt/sources.list.d/bazel.list

# Install build dependencies and Bazel.
RUN apt update && \
  apt full-upgrade -y && \
  DEBIAN_FRONTEND=noninteractive apt install -y \
    bazel \
    git \
    python-is-python3 \
    python3-pip \
    && \
  apt clean && \
  apt autoremove -y

RUN \
  apt remove -y \
    curl \
    gnupg2

# For Ansible
RUN pip3 install ansible ansible-lint
