# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "AI OCA MCP OAuth",
    "summary": "OAuth 2.0 support for Odoo MCP servers",
    "version": "18.0.1.0.0",
    "license": "AGPL-3",
    "author": "Dixmit,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/ai",
    "depends": [
        "ai_oca_mcp",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/mcp_server.xml",
        "views/mcp_server_key.xml",
        "wizards/mcp_server_key_add.xml",
    ],
    "post_init_hook": "post_init_hook",
    "demo": [],
}
