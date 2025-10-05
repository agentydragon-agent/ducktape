export type McpPreset = {
  id: string
  label: string
  transport: 'stdio' | 'sse' | 'inproc'
  defaultName?: string
  defaults: {
    stdio?: { command: string; args: any[]; env: Record<string, string> }
    sse?: { url: string; headers: Record<string, string>; timeout_secs: number; sse_read_timeout_secs: number }
    inproc?: { factory: string; args: any[]; kwargs: Record<string, any> }
  }
}

export const MCP_PRESETS: McpPreset[] = [
  {
    id: 'stdio_template',
    label: 'Stdio Template',
    transport: 'stdio',
    defaultName: 'server',
    defaults: {
      stdio: {
        command: '/usr/bin/env',
        args: ['server-binary'],
        env: {},
      },
    },
  },
  {
    id: 'seatbelt_exec',
    label: 'Seatbelt Exec (inproc)',
    transport: 'inproc',
    defaultName: 'seatbelt',
    defaults: {
      inproc: {
        factory: 'adgn.mcp.seatbelt_exec.server:make_seatbelt_exec_mcp',
        args: [],
        kwargs: { name: 'seatbelt' },
      },
    },
  },
]
