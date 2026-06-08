# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class McpServerKeyAdd(models.TransientModel):
    _inherit = "mcp.server.key.add"

    server_auth_type = fields.Selection(related="server_id.auth_type", readonly=True)

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        server_id = result.get("server_id") or self.env.context.get("default_server_id")
        if server_id:
            server = self.env["mcp.server"].browse(server_id)
            if server.auth_type == "oauth":
                result["auth_type"] = "oauth"
            elif server.auth_type in ("bearer", "bearer_oauth"):
                result.setdefault("auth_type", "bearer")
        return result

    @api.onchange("server_id")
    def _onchange_server_id_auth_type(self):
        if self.server_id.auth_type == "oauth":
            self.auth_type = "oauth"
        elif self.server_id.auth_type == "bearer":
            self.auth_type = "bearer"

    def generate_key(self):
        if self.auth_type == "oauth" and not self.server_id._is_oauth_auth_enabled():
            raise UserError(_("OAuth 2.0 is not enabled on this MCP server."))
        if self.auth_type == "bearer" and not self.server_id._is_bearer_auth_enabled():
            raise UserError(_("Bearer Token is not enabled on this MCP server."))
        return super().generate_key()
