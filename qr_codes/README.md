# QR Codes

SVG QR codes for places around the house.

## Generating

Requires Bebas Neue installed as a system font (via home-manager on wyrm2).

```bash
bazel run //qr_codes:gen -- \
  --text 'TEXT_TO_ENCODE' \
  --caption 'Caption below code' \
  --output path/to/output.svg
```

## Codes

| File                    | Text                      | Caption             |
| ----------------------- | ------------------------- | ------------------- |
| `bathroom_15_leroy.svg` | `15 Leroy Place bathroom` | Rai's morning alarm |
