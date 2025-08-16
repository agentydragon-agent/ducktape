// 2025-08-14: Claude CLI changelog claims to have fixed the heredoc escaping issue, so this is not needed anymore.
//
/**
 * BashDisclaimerTransformer
 * Order: place LAST in the transformer chain (after any Anthropic→OpenAI mapping) so it patches the final tool/function schema.
 * Matching: only applies to the exact tool/function name 'Bash'. If placed earlier with other names (e.g. 'bash'), it will not run.
 */

// TODO: additional transformer: detect errors after commands that heuristically look like they would fail (e.g. python << heredoc) and augment error message.
class BashDisclaimerTransformer {
  constructor(options = {}) {
    this.name = 'bash-disclaimer'
    this.disclaimer = (options.text || [
      'Bash tool guidance and environment mechanics:',
      '- Commands execute as eval "<cmd>" "<" "/dev/null"; stdin is /dev/null. Heredocs and pipelines whose last stage reads stdin will break.',
      "- '!' triggers history expansion; the tool auto-escapes to \\! in double-quoted payloads, which breaks any code with ! (e.g., node -e 'if(!x){...}').",
      'Use these patterns instead:',
      '- Short snippets: python -c "print(\'ok\')".',
      // "- Multi-line: write a file and run it (avoid heredocs reading stdin).",
      "- If you must use a heredoc, wrap inside: bash -lc \"python - <<'PY'\\nprint('ok')\\nPY\".",
      "- For jq at pipeline end, pass an explicit file (e.g., jq '.prog' input.json).",
      "- Avoid '!' in inline -e one-liners; prefer temp files or heredoc via bash -lc, or use jq for JSON edits.",
      '- Prefer jq for JSON edits over node -e to avoid quoting/expansion pitfalls.'
    ].join('\n')).trim()
  }

  transformRequestIn(request) { return this.#apply(request) }
  transformRequestOut(request) { return this.#apply(request) }

  #apply(request) {
    const r = JSON.parse(JSON.stringify(request))
    if (Array.isArray(r.tools)) r.tools = r.tools.map((t) => this.#patchTool(t))
    if (Array.isArray(r.functions)) r.functions = r.functions.map((f) => this.#patchFunction(f))
    if (Array.isArray(r.messages)) r.messages = r.messages.map((m) => this.#patchToolDefsInMessage(m))
    return r
  }

  #patchTool(t) {
    if (t && typeof t === 'object') {
      if (t.function && t.function.name === 'Bash') {
        const d = String(t.function.description || '')
        if (!d.includes('Bash tool guidance and environment mechanics:') && !d.includes('stdin is /dev/null')) {
          t.function.description = this.#rewriteDescription(d)
        }
      } else if (t.name === 'Bash' || t.type === 'Bash') {
        const d = String(t.description || '')
        if (!d.includes('Bash tool guidance and environment mechanics:') && !d.includes('stdin is /dev/null')) {
          t.description = this.#rewriteDescription(d)
        }
      }
    }
    return t
  }

  #patchFunction(f) {
    if (f && typeof f === 'object' && f.name === 'Bash') {
      const d = String(f.description || '')
      if (!d.includes('Bash tool guidance and environment mechanics:') && !d.includes('stdin is /dev/null')) {
        f.description = this.#rewriteDescription(d)
      }
    }
    return f
  }

  #rewriteDescription(orig) {
    try {
      const s = String(orig || '')
      if (s.includes('Bash tool guidance and environment mechanics:') || s.includes('stdin is /dev/null')) return s
      const anchor1 = 'Usage notes:'
      const anchor2 = 'Before executing the command'
      const caveats = [
        'Environment caveats:',
        '- Commands execute as eval "<cmd>" "<" "/dev/null"; stdin is /dev/null. Heredocs and pipelines whose last stage reads stdin will break.',
        "- '!' triggers history expansion; the tool auto-escapes to \\! in double-quoted payloads, which breaks any code with ! (e.g., node -e 'if(!x){...}').",
        'Use these patterns instead:',
        '- Short snippets: python -c "print(\'ok\')".',
        '- Multi-line: write a file and run it (avoid heredocs reading stdin).',
        "- If you must use a heredoc, wrap inside: bash -lc \"python - <<'PY'\\nprint('ok')\\nPY\".",
        "- For jq at pipeline end, pass an explicit file (e.g., jq '.prog' input.json).",
        "- Avoid '!' in inline -e one-liners; prefer temp files or heredoc via bash -lc, or use jq for JSON edits.",
        '- Prefer jq for JSON edits over node -e to avoid quoting/expansion pitfalls.'
      ].join('\n')
      if (s.includes(anchor1)) return s.replace(anchor1, `${caveats}\n\n${anchor1}`)
      if (s.includes(anchor2)) return s.replace(anchor2, `${caveats}\n\n${anchor2}`)
      return `${caveats}\n\n${s}`.trim()
    } catch (_) {
      return `${this.disclaimer}\n\n${String(orig || '')}`.trim()
    }
  }

  #patchToolDefsInMessage(m) {
    if (!m || !Array.isArray(m.content)) return m
    const content = m.content.map((c) => {
      if (c && c.type === 'tool_definitions' && Array.isArray(c.tools)) {
        return { ...c, tools: c.tools.map((t) => this.#patchTool(t)) }
      }
      return c
    })
    return { ...m, content }
  }
}

module.exports = BashDisclaimerTransformer
