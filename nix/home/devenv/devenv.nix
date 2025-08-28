{ pkgs, config, lib, ... }:

let
  # Generate MCP config file in Nix
  mcpConfig = pkgs.writeText "mcp-template.json" (builtins.toJSON {
    mcpServers = {
      local-sqlite = {
        url = "http://localhost:__MCP_PORT__";
        transport = { type = "sse"; };
        description = "Local SQLite MCP server";
      };
      local-files = {
        url = "http://localhost:__WEB_PORT__";
        transport = { type = "http"; };
        description = "Local file server";
      };
    };
  });
in
{
  # Dependencies
  packages = [ pkgs.nodejs pkgs.python3 ];

  # Python virtual environment
  languages.python = {
    enable = true;
    venv.enable = true;
  };

  # Auto-allocated ports
  env = {
    MCP_PORT = "$(devenv port get mcp 2>/dev/null || devenv port allocate mcp)";
    WEB_PORT = "$(devenv port get web 2>/dev/null || devenv port allocate web)";
  };

  # Services
  processes = {
    mcp = { exec = "npx @modelcontextprotocol/server-sqlite --port $MCP_PORT"; };
    web = { exec = "python -m http.server $WEB_PORT"; };
  };

  enterShell = ''
    echo "MCP: http://localhost:$MCP_PORT"
    echo "Web: http://localhost:$WEB_PORT"

    # Generate .mcp.json from Nix template
    ${pkgs.gnused}/bin/sed \
      -e "s/__MCP_PORT__/$MCP_PORT/g" \
      -e "s/__WEB_PORT__/$WEB_PORT/g" \
      ${mcpConfig} > .mcp.json

    echo "Generated .mcp.json with allocated ports"
  '';
}
