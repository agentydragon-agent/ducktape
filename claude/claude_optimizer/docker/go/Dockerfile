FROM claude-base:latest

# Install Go
RUN wget https://go.dev/dl/go1.21.5.linux-amd64.tar.gz \
    && tar -C /usr/local -xzf go1.21.5.linux-amd64.tar.gz \
    && rm go1.21.5.linux-amd64.tar.gz

ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/workspace/go"
ENV GOBIN="${GOPATH}/bin"

# Install common Go tools
RUN go install golang.org/x/tools/cmd/goimports@latest \
    && go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

LABEL dev.environment="go"
LABEL dev.description="Go development environment with common tools"