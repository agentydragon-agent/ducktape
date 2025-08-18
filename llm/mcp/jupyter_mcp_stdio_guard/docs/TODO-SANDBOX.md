# TODO — Sandbox Hardening and Options

- Network egress options:
  - Add a mode to allow only loopback + a local HTTP proxy, and restrict that proxy to a curated allowlist (e.g., openai.com) while denying general HTTP
- Filesystem surface:
  - Reduce file-read* to the minimum required (system libs, site-packages) and keep WORKSPACE read/write; make /tmp writes optional
- Policy capabilities:
  - Support specifying policy sections/capabilities on argv (seatbelt substitutions), to toggle features without changing code
- Environment hygiene:
  - Allow only a curated set of env vars to reach the kernel; strip the rest by default, with an opt-in allowlist
