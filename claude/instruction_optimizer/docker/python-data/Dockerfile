FROM claude-base:latest

# Install Python with data science packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install data science packages
RUN pip3 install --no-cache-dir \
    pandas \
    numpy \
    scikit-learn \
    matplotlib \
    seaborn \
    jupyter \
    sqlalchemy \
    psycopg2-binary \
    requests \
    pytest \
    black \
    ruff

# Set Python as default
RUN ln -sf /usr/bin/python3 /usr/bin/python

LABEL dev.environment="python-data"
LABEL dev.description="Python data science environment with pandas, numpy, sklearn"