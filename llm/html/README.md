# LLM HTML Instructions Server

A FastAPI server that renders Markdown instructions with dynamic token generation for LLM authentication.

## Running the server

```bash
# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server
python html_server.py

# Or with custom settings
TOKEN_SECRET=mysecret PORT=8080 python html_server.py
```

The server will start on http://localhost:9000 by default.

## Docker

```bash
# Build and run with Docker
./build_and_run.sh
```

## Environment variables

- `TOKEN_SECRET`: Secret key for token generation (default: 'hunter2')
- `HOST`: Host to bind to (default: '0.0.0.0')
- `PORT`: Port to listen on (default: 9000)