# Props cluster deployment — TODOs

- [ ] **Seal the OpenAI API key**: The SealedSecret at
      `props-secrets/openai-api-key-sealed.yaml` has a placeholder `REPLACE_ME`
      value. Seal with:
      `scripts/seal-secret.sh props props-openai-api-key api-key <your-openai-key>`
- [ ] Ensure Ollama has `gpt-oss-20b` model pulled
