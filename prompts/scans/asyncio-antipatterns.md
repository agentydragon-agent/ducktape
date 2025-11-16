# Scan: Asyncio Antipatterns

## Context
@../shared-context.md

## Pattern 1: Synchronous I/O in Async Functions

### Example: Blocking file operations

```python
# BAD: Synchronous file I/O in async function
async def read_config(path: Path) -> dict:
    content = path.read_text()  # Blocks event loop!
    return json.loads(content)

# ACCEPTABLE: Use asyncio.to_thread for blocking I/O
async def read_config(path: Path) -> dict:
    content = await asyncio.to_thread(path.read_text)
    return json.loads(content)

# BEST: Use proper async file I/O library (for frequent/large file operations)
import aiofiles
async def read_config(path: Path) -> dict:
    async with aiofiles.open(path, 'r') as f:
        content = await f.read()
    return json.loads(content)
```

Issues:
- Blocks the event loop, preventing other coroutines from running
- Defeats the purpose of async/await
- Can cause performance degradation under load
- **Note**: For infrequent small file reads, `asyncio.to_thread()` is acceptable
- **Note**: For frequent or large file I/O, use `aiofiles` or similar async file library

### Example: Blocking subprocess calls

```python
# BAD: Blocking subprocess.run in async function
async def get_git_status():
    result = subprocess.run(["git", "status"], capture_output=True)
    return result.stdout.decode()

# GOOD: Use asyncio.create_subprocess_exec
async def get_git_status():
    proc = await asyncio.create_subprocess_exec(
        "git", "status",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
```

Issues:
- `subprocess.run()` blocks until process completes
- Event loop stalls for entire subprocess duration
- Other async tasks cannot make progress

### Example: os.write/os.read without non-blocking mode

```python
# BAD: Synchronous os.write in async function
async def write_to_pipe(fd: int, data: bytes):
    os.write(fd, data)  # Can block!

# ACCEPTABLE: Use asyncio.to_thread for write (but not ideal)
async def write_to_pipe(fd: int, data: bytes):
    await asyncio.to_thread(os.write, fd, data)

# BEST: Use proper asyncio streams with non-blocking FD
async def write_to_pipe(fd: int, data: bytes):
    import fcntl
    # Set FD to non-blocking for asyncio
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Create asyncio StreamWriter from the FD
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, os.fdopen(fd, 'wb', buffering=0)
    )
    writer = asyncio.StreamWriter(transport, protocol, None, loop)

    try:
        writer.write(data)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
```

Issues:
- `os.write()` and `os.read()` can block if buffer is full/empty
- `asyncio.to_thread()` works but adds thread overhead
- **BEST**: Use native asyncio streams with non-blocking FDs for true async I/O

### Example: os.fdopen without non-blocking FD

```python
# BAD: Opening blocking FD for asyncio use
async def read_from_pipe(fd: int):
    pipe_file = os.fdopen(fd, "rb")  # FD is blocking!
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, pipe_file)

# GOOD: Set FD to non-blocking first
async def read_from_pipe(fd: int):
    import fcntl
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    pipe_file = os.fdopen(fd, "rb", buffering=0)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, pipe_file)
```

Issues:
- File descriptors are blocking by default
- asyncio expects non-blocking FDs for stream operations
- Can cause event loop stalls

## Pattern 2: Deprecated Event Loop APIs

### Example: asyncio.get_event_loop()

```python
# BAD: Using deprecated get_event_loop
async def process_data():
    loop = asyncio.get_event_loop()  # Deprecated!
    # ... use loop ...

# GOOD: Use get_running_loop
async def process_data():
    loop = asyncio.get_running_loop()
    # ... use loop ...
```

Issues:
- `asyncio.get_event_loop()` is deprecated in Python 3.10+
- May return None if no event loop is running
- `get_running_loop()` raises clear error if called outside async context

### Example: asyncio.run() in non-entry-point code

```python
# BAD: asyncio.run() nested in async code
async def helper():
    result = asyncio.run(some_async_task())  # Error! Already in event loop
    return result

# GOOD: Just await it
async def helper():
    result = await some_async_task()
    return result

# ACCEPTABLE: Only in top-level entry points
if __name__ == "__main__":
    asyncio.run(main())
```

Issues:
- `asyncio.run()` creates a new event loop
- Cannot be called from within an existing event loop
- Raises `RuntimeError: asyncio.run() cannot be called from a running event loop`

## Pattern 3: Subprocess Antipatterns

### Example: subprocess.Popen without async wrapper

```python
# BAD: Using Popen directly in async code
async def run_command(cmd: list[str]):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)  # ASYNC220
    stdout, _ = proc.communicate()  # Blocks!
    return stdout

# GOOD: Use asyncio subprocess
async def run_command(cmd: list[str]):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout
```

Issues:
- `subprocess.Popen()` and `.communicate()` are blocking
- Ruff ASYNC220 warns about this
- Event loop cannot schedule other tasks during subprocess execution

### Example: subprocess.run() in async function

```python
# BAD: subprocess.run blocks event loop
async def check_git_status():
    result = subprocess.run(["git", "status"], capture_output=True)
    return result.returncode == 0

# GOOD: Use asyncio subprocess or to_thread
async def check_git_status():
    proc = await asyncio.create_subprocess_exec(
        "git", "status",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()
    return proc.returncode == 0

# ALTERNATIVE: Wrap in to_thread if you need subprocess.run features
async def check_git_status():
    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "status"],
        capture_output=True
    )
    return result.returncode == 0
```

## Pattern 4: Synchronous Network I/O

### Example: Blocking socket operations

```python
# BAD: Using synchronous socket in async function
async def fetch_data(host: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))  # Blocks!
    data = sock.recv(1024)  # Blocks!
    return data

# GOOD: Use asyncio streams
async def fetch_data(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)
    data = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    return data
```

## Pattern 5: Improperly Handling CPU-Bound Work

### Example: CPU-intensive work in async function

```python
# BAD: CPU-bound work blocks event loop
async def compute_hash(data: bytes):
    return hashlib.sha256(data * 10000000).hexdigest()  # Blocks for seconds!

# GOOD: Use asyncio.to_thread for CPU-bound work
async def compute_hash(data: bytes):
    return await asyncio.to_thread(
        lambda: hashlib.sha256(data * 10000000).hexdigest()
    )

# BETTER: Use ProcessPoolExecutor for true parallelism
async def compute_hash(data: bytes):
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool, hashlib.sha256(data * 10000000).hexdigest
        )
    return result
```

## Detection Heuristics

### 1. Blocking I/O in async functions

```bash
# Find path.read_text/write_text in async functions
rg --type py -U 'async def.*\n.*\n.*\.(read_text|write_text|read_bytes|write_bytes)'

# Find open() in async functions
rg --type py -U 'async def.*\n.*\n.*\bopen\('

# Find os.read/os.write in async functions
rg --type py -U 'async def.*\n.*\n.*os\.(read|write)\('
```

### 2. Deprecated event loop APIs

```bash
# Find get_event_loop() usage (deprecated)
rg --type py 'asyncio\.get_event_loop\(\)'

# Find asyncio.run() outside main entry points
rg --type py 'asyncio\.run\(' | grep -v '__main__' | grep -v '^if __name__'
```

### 3. Subprocess antipatterns

```bash
# Find subprocess.run in async functions
rg --type py -U 'async def.*\n.*\n.*subprocess\.run\('

# Find subprocess.Popen in async functions
rg --type py -U 'async def.*\n.*\n.*subprocess\.Popen\('

# Find .communicate() without await
rg --type py '\.communicate\(\)' | grep -v 'await'
```

### 4. FD operations without non-blocking mode

```bash
# Find os.fdopen without O_NONBLOCK check
rg --type py 'os\.fdopen\(' -A5 -B5 | grep -L 'O_NONBLOCK'

# Find os.pipe() without O_NONBLOCK setup
rg --type py 'os\.pipe\(\)' -A10 | grep -L 'O_NONBLOCK'
```

### 5. Sync operations on streams/sockets

```bash
# Find socket operations in async functions
rg --type py -U 'async def.*\n.*\n.*(socket\..*\.connect|socket\..*\.recv|socket\..*\.send)\('
```

## Fix Strategy

1. **Identify blocking I/O**: Any file, network, or subprocess operation
2. **Choose the right async primitive** (in order of preference):
   - **BEST**: Native asyncio methods (streams, subprocess, connections)
   - **ACCEPTABLE**: `asyncio.to_thread()` for unavoidable blocking operations
   - **AVOID**: Direct blocking calls in async functions
3. **Specific guidelines**:
   - File I/O → `aiofiles` (best) or `asyncio.to_thread(path.read_text)` (acceptable)
   - Subprocess → `asyncio.create_subprocess_exec()` (best, never `subprocess.run()`)
   - Network → `asyncio.open_connection()` / `asyncio.open_unix_connection()` (best)
   - Pipe/FD I/O → asyncio streams with `O_NONBLOCK` (best) or `asyncio.to_thread()` (acceptable)
   - CPU-bound → `asyncio.to_thread()` or `ProcessPoolExecutor`
4. **Set FDs to non-blocking**: Use `fcntl` to set `O_NONBLOCK` before asyncio use
5. **Use modern APIs**: Replace `get_event_loop()` with `get_running_loop()`
6. **Never nest asyncio.run()**: Only use in top-level entry points

### Preference Hierarchy

1. **Native asyncio** (e.g., `asyncio.create_subprocess_exec`, `asyncio.open_connection`, asyncio streams)
   - True async I/O, no thread overhead
   - Full integration with event loop
   - Best performance and scalability

2. **`asyncio.to_thread()`** (for unavoidable blocking operations)
   - When no native asyncio alternative exists
   - For quick/infrequent blocking operations
   - Adds thread pool overhead

3. **Never acceptable**: Direct blocking calls in async functions
   - Defeats the entire purpose of async/await
   - Blocks event loop, preventing all other tasks

## Real-World Example: Handshake Pipe Communication

This example shows the complete fix for async pipe-based handshake communication between a client and daemon process.

### Client side: Reading from handshake pipe

```python
# BAD: Blocking FD used with asyncio
async def _read_handshake_from_pipe(self):
    # Create pipe without setting non-blocking
    read_fd, write_fd = os.pipe()

    # Use deprecated API
    loop = asyncio.get_event_loop()

    # Open blocking FD for asyncio use
    pipe_file = os.fdopen(read_fd, "rb", buffering=0)
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, pipe_file)

# GOOD: Non-blocking FD with modern asyncio
async def _read_handshake_from_pipe(self):
    # Create pipe and set read end to non-blocking
    read_fd, write_fd = os.pipe()
    import fcntl
    flags = fcntl.fcntl(read_fd, fcntl.F_GETFL)
    fcntl.fcntl(read_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Use modern get_running_loop (Python 3.10+)
    loop = asyncio.get_running_loop()

    # Open non-blocking FD for asyncio use
    pipe_file = os.fdopen(read_fd, "rb", buffering=0)
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, pipe_file)

    # Read asynchronously
    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            break
        # Process line...
```

### Server side: Writing to handshake pipe

```python
# BAD: Blocking os.write from async function
async def write_startup_handshake(**data):
    handshake_fd = int(os.environ.get("WT_HANDSHAKE_FD"))
    payload = json.dumps(data).encode() + b"\n"

    # Blocks event loop!
    os.write(handshake_fd, payload)

# ACCEPTABLE: Thread-based approach (adds overhead)
async def write_startup_handshake(**data):
    handshake_fd = int(os.environ.get("WT_HANDSHAKE_FD"))
    payload = json.dumps(data).encode() + b"\n"

    # Works but uses thread pool
    await asyncio.to_thread(os.write, handshake_fd, payload)

# BEST: Native asyncio streams
async def write_startup_handshake(**data):
    handshake_fd = int(os.environ.get("WT_HANDSHAKE_FD"))
    payload = json.dumps(data).encode() + b"\n"

    import fcntl
    # Set FD to non-blocking
    flags = fcntl.fcntl(handshake_fd, fcntl.F_GETFL)
    fcntl.fcntl(handshake_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Create asyncio StreamWriter
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin,
        os.fdopen(handshake_fd, 'wb', buffering=0)
    )
    writer = asyncio.StreamWriter(transport, protocol, None, loop)

    try:
        writer.write(payload)
        await writer.drain()  # True async write
    finally:
        writer.close()
        await writer.wait_closed()
```

**Key improvements**:
- Set FDs to `O_NONBLOCK` before asyncio use
- Use `asyncio.get_running_loop()` instead of deprecated `get_event_loop()`
- Use native asyncio streams instead of `asyncio.to_thread()` for true async I/O
- Proper cleanup with `writer.close()` and `await writer.wait_closed()`

## References

- [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html)
- [asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html)
- [Event Loop APIs](https://docs.python.org/3/library/asyncio-eventloop.html)
- [Ruff ASYNC rules](https://docs.astral.sh/ruff/rules/#flake8-async-async)
