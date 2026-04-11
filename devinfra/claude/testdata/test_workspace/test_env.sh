#!/usr/bin/env bash
# Demonstrative env script for the container e2e test.
# Outputs a known test variable so the test can verify env script execution.
printf 'export E2E_TEST_SECRET=%q\n' "hello-from-env-script"
