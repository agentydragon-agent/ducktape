# Upload vocabulary

- ```bash
  bazel run @solid_cli//:solid_cli -- \
  --command=createfile \
  --url='https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl' \
  --mimetype=text/turtle \
  --filepath=$(pwd)/vocabulary.ttl
  ```

# Upload snapshot

- set credentials:
  ```bash
  export SOLID_USERNAME=agentydragon
  export SOLID_PASSWORD=<...>
  ```
- upload the snapshot:
  ```bash
  bazel run //worthy -- --write_to_solid
  ```
