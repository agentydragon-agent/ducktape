## Building

```bash
docker build -t registry.gitlab.com/agentydragon/playbooks/cirunner .
```

## Pushing

Get personal access token from: https://gitlab.com/-/profile/personal_access_tokens

```bash
docker login registry.gitlab.com -u agentydragon -p <token>
```

```bash
docker push registry.gitlab.com/agentydragon/playbooks/cirunner
```

