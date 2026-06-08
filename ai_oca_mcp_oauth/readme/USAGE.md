- Install this module together with `ai_oca_mcp`.
- Go to `AI > MCP Server`.
- Select **OAuth 2.0** or **Bearer Token and OAuth 2.0** in the authentication
  mode.
- Add the MCP server `URL` to Claude as a remote custom connector.

Claude discovers the OAuth metadata from the MCP endpoint, opens the Odoo
authorization flow, and then calls the MCP endpoint with the issued access token.
