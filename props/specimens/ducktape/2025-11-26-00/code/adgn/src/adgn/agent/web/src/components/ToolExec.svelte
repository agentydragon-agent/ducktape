<script lang="ts">
  import type { ToolItem, ExecContent } from '../../shared/types'
  import JsonDisclosure from './JsonDisclosure.svelte'

  export let item: ToolItem

  // Use discriminated union type guard for type-safe access
  $: execContent = item.content?.content_kind === 'Exec' ? item.content : null

  function copyText(text: string) {
    if (!text) return
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).catch(() => {})
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } finally { document.body.removeChild(ta) }
    }
  }

  function copyExec() {
    if (!execContent) return
    const parts: string[] = []
    if (execContent.cmd) parts.push(`$ ${execContent.cmd}`)
    if (execContent.stdout) parts.push(String(execContent.stdout))
    if (execContent.stderr) parts.push(String(execContent.stderr))
    copyText(parts.join('\n'))
  }

</script>

<div class="terminal">
  <div class="kind">{item.tool} {#if item.decision}<span class="term-approval">[{item.decision}]</span>{/if}
    <button class="copy" title="Copy output" on:click={copyExec}>Copy</button>
  </div>
  {#if typeof item.tool === 'string' && item.tool.endsWith('__sandbox_exec') && execContent}
    <JsonDisclosure label="SBPL Policy" value={execContent.args?.policy} persistKey={`sbpl:${item.id}`} />
    <JsonDisclosure label="Raw output (JSON)" value={execContent} persistKey={`execraw:${item.id}`} />
  {/if}
  <div class="terminal-body">
    {#if execContent?.cmd}
      <pre class="term-line">$ {execContent.cmd}</pre>
    {/if}
    {#if execContent?.stdout}
      <pre class="term-stdout">{execContent.stdout}</pre>
    {/if}
    {#if execContent?.stderr}
      <pre class="term-stderr">{execContent.stderr}</pre>
    {/if}
    {#if execContent?.exit_code !== null && execContent?.exit_code !== undefined}
      <div class="term-exit">[exit {execContent.exit_code}]</div>
    {/if}
    {#if execContent?.is_error}
      <div class="term-error">[error]</div>
    {/if}
  </div>
</div>

<style>
  .terminal .terminal-body { background: #111; color: #eee; border-radius: 6px; padding: 0.5rem; max-height: 18rem; overflow: auto; }
  .terminal pre { margin: 0.25rem 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.85rem; line-height: 1.35; }
  .term-line { color: #9cdcfe; }
  .term-stdout { color: #d4d4d4; }
  .term-stderr { color: #f28b82; }
  .term-exit { color: #8ab4f8; font-size: 0.75rem; margin: 0.1rem 0 0.4rem; }
  .term-error { color: #ffb4ab; font-size: 0.75rem; margin: 0.2rem 0; }
  .term-approval { color: #ffd54f; font-size: 0.8rem; margin: 0.1rem 0; }
  .copy { margin-left: 0.5rem; font-size: 0.7rem; padding: 0.1rem 0.4rem; }
</style>
