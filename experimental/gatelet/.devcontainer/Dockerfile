FROM python:3.11-slim

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        bash-completion \
        build-essential \
        gcc \
        postgresql-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Install Python dependencies
COPY experimental/gatelet/requirements*.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ -f requirements-dev.txt ]; then pip install -r requirements-dev.txt; fi

# Create a non-root user for development
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && apt-get update \
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# Set up home directory for the non-root user
USER $USERNAME
ENV HOME /home/$USERNAME

# Set up bash completion and aliases
RUN echo "source /etc/bash_completion" >> ~/.bashrc \
    && echo "alias ll='ls -al'" >> ~/.bashrc \
    && echo "alias python='python3'" >> ~/.bashrc

# Switch back to root for operations that require it
USER root