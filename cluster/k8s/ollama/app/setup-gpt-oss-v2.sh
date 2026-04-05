#!/bin/sh
set -e
ollama pull gpt-oss:20b
ollama pull gpt-oss:120b
ollama pull gemma4:31b-it-q8_0
