#!/bin/sh
# initContainer script: fetch the pinned static stalwart-cli release binary
# into the shared /cli volume for bootstrap-and-run.sh. Runs on alpine because
# neither Stalwart image can do this itself: ghcr.io/stalwartlabs/cli is
# distroless (a bare static binary — no shell to copy it out with) and the
# server image lacks xz to unpack the release tarball.
set -eu

VERSION=v1.0.10
TARBALL=stalwart-cli-x86_64-unknown-linux-musl.tar.xz
SHA256=d1713cd4e00908af02d372d1a9e44e9df69182ab5caf8481557f0eb1b22ea5f5

cd /tmp
wget -q "https://github.com/stalwartlabs/cli/releases/download/${VERSION}/${TARBALL}"
echo "${SHA256}  ${TARBALL}" | sha256sum -c -
tar -xJf "${TARBALL}"
cp "${TARBALL%.tar.xz}/stalwart-cli" /cli/stalwart-cli
