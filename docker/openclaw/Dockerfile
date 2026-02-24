# Custom OpenClaw image with matrix channel plugin pre-installed.
#
# The upstream image bundles extension source at /app/extensions/matrix/ but not
# its npm dependencies. `plugins install` copies to CONFIG_DIR/extensions/ and
# runs npm install. We bake this into the image so no init container is needed.
#
# The crypto native binary (matrix-sdk-crypto-nodejs) must be downloaded manually
# because openclaw runs `npm install --ignore-scripts` (security hardening).
FROM ghcr.io/openclaw/openclaw:2026.2.23

USER root
RUN node --max-old-space-size=1024 openclaw.mjs plugins install /app/extensions/matrix \
 && CRYPTO_DIR=$(find /home/node/.openclaw -path '*/matrix-sdk-crypto-nodejs' -type d | head -1) \
 && if [ -n "$CRYPTO_DIR" ]; then \
      wget -q -O "$CRYPTO_DIR/matrix-sdk-crypto.linux-x64-gnu.node" \
        "https://github.com/matrix-org/matrix-rust-sdk-crypto-nodejs/releases/download/v0.4.0/matrix-sdk-crypto.linux-x64-gnu.node"; \
    fi \
 && chown -R node:node /home/node/.openclaw
USER node
