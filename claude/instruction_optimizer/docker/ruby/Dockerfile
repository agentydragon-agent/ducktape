FROM claude-base:latest

# Install Ruby via RVM for better version management
RUN apt-get update && apt-get install -y \
    curl \
    gnupg2 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install RVM and Ruby
RUN gpg2 --recv-keys 409B6B1796C275462A1703113804BB82D39DC0E3 7D2BAF1CF37B13E2069D6956105BD0E739499BDB \
    && curl -sSL https://get.rvm.io | bash -s stable --ruby

# Set up RVM environment
ENV PATH="/usr/local/rvm/bin:${PATH}"
RUN /bin/bash -l -c "rvm use --default ruby"
RUN /bin/bash -l -c "gem install bundler sqlite3 json httparty colorize"

LABEL dev.environment="ruby"
LABEL dev.description="Ruby development environment with common gems"