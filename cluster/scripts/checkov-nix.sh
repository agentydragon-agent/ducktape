#!/bin/bash
exec nix-shell -p checkov --run "checkov $*"