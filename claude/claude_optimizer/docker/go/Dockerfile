FROM claude-base:latest

# Switch to root to install Go
USER root

# Install Go
RUN curl -L https://go.dev/dl/go1.21.5.linux-amd64.tar.gz -o go1.21.5.linux-amd64.tar.gz \
    && tar -C /usr/local -xzf go1.21.5.linux-amd64.tar.gz \
    && rm go1.21.5.linux-amd64.tar.gz \
    && chmod -R 755 /usr/local/go

# Switch back to node user
USER node

ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/home/node/go"
ENV GOBIN="${GOPATH}/bin"
ENV PATH="${GOBIN}:${PATH}"

# Install common Go tools
RUN go install golang.org/x/tools/cmd/goimports@latest \
    && go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

LABEL dev.environment="go"
LABEL dev.description="Go development environment with common tools"