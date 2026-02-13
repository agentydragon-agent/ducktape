Secrets: age-encrypted secrets were decrypted and injected into your environment.
`GITHUB_TOKEN`: Full-access GitHub PAT for the `agentydragon-agent` bot account. Used by `gh` CLI automatically. Supports all read/write operations including push, PR create/update, issue management.
`OLLAMA_BASE_URL`: OpenAI-compatible API endpoint for Ollama (self-hosted LLM inference with 2x RTX 5090). Use with OpenAI SDK: `OpenAI(base_url=os.environ["OLLAMA_BASE_URL"], api_key=os.environ["OLLAMA_API_KEY"])`.
`OLLAMA_API_KEY`: Bearer token for Ollama API authentication.
