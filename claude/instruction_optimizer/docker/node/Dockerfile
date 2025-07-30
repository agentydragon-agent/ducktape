FROM claude-base:latest

# Install Node.js via NodeSource repository
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Install global npm packages
RUN npm install -g \
    typescript \
    ts-node \
    @types/node \
    jest \
    eslint \
    prettier \
    nodemon

LABEL dev.environment="node"
LABEL dev.description="Node.js development environment with TypeScript and common tools"