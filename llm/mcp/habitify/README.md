# Habitify MCP Server

A Python Model Context Protocol (MCP) server for interacting with the Habitify habit tracking API. This server allows Claude AI to help you track and manage your habits through the Habitify service.

## Features

- View your habits and check their status
- Track habit completion with different statuses (completed, skipped, failed)
- Support for both single-date and date-range status queries
- Create, update and delete habits through Claude
- Full integration with Claude Desktop through MCP tools
- Support for both stdio and SSE transports
- Clean error handling with helpful messages

## Installation

### Requirements

- Python 3.8 or higher
- A Habitify API key (from your Habitify account)
- The MCP SDK (for installing to Claude Desktop)

### Install Dependencies

```bash
# Clone the repository
git clone https://github.com/example/habitify-mcp-py.git
cd habitify-mcp-py

# Install dependencies
pip install -r requirements.txt

# For development
pip install -e ".[dev]"
```

### Configure API Key

There are multiple ways to provide your Habitify API key:

1. **Environment variable** (recommended for security):
   ```bash
   export HABITIFY_API_KEY=your_api_key_here
   habitify ...
   ```

2. **.env file**:
   Create a `.env` file in the project directory:
   ```
   HABITIFY_API_KEY=your_api_key_here
   ```
   Note: Make sure `.env` files are listed in your `.gitignore` to prevent accidental commits of API keys.

3. **Commandline argument** (not recommended for shared systems):
   ```bash
   habitify --api-key=your_api_key_here ...
   ```
   
> **Security Note:** Your API key provides full access to your Habitify account. Never commit it to version control or share it publicly. The `.gitignore` file in this repository is configured to exclude `.env` files.

## Usage

### Install to Claude Desktop

The easiest way to use this MCP server is to install it directly to Claude Desktop:

```bash
# Install to Claude with API key from environment or .env file
habitify install

# Or specify API key directly
habitify install --api-key=your_api_key_here

# Optionally change the server name
habitify install --name="My Habitify"
```

### Run the Server Manually

You can also run the server manually:

```bash
# Run with stdio transport (default, for direct use with Claude)
habitify mcp

# Run with SSE transport (for web integration)
habitify mcp --transport=sse --port=5000

# Run with debug logging
habitify mcp --debug
```

## Development

### Run Tests

```bash
pytest
```

### Code Quality

```bash
# Run linters
black habitify_mcp_server
isort habitify_mcp_server
```

## API Reference Examples

The `habitify_api_reference` directory contains examples of API requests and responses for all Habitify API endpoints, useful for development and testing.

To collect fresh reference examples (requires an API key):

```bash
python habitify_api_reference/collect_references.py
```

## License

MIT
