This directory builds the Docker image used for CI for this project.
Unfortunately Bazel only supports `amd64` right now, so this image won't work
on any other platform.

## Updating Bazel release key

```bash
curl -fsSL https://bazel.build/bazel-release.pub.gpg | gpg --dearmor > bazel.gpg
```

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

## Testing

```bash
docker build .
