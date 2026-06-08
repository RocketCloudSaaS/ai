# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, tools


class McpServerKey(models.Model):
    _inherit = "mcp.server.key"

    auth_type = fields.Selection(
        [("bearer", "Bearer Token"), ("oauth", "OAuth 2.0")],
        default="bearer",
        required=True,
        index=True,
    )
    refresh_token_hash = fields.Char(copy=False, groups="base.group_system")
    oauth_client_id = fields.Many2one(
        "mcp.oauth.client",
        ondelete="cascade",
        readonly=True,
    )
    scope = fields.Char(readonly=True)

    def _is_enabled_by_server(self):
        self.ensure_one()
        if self.auth_type == "oauth":
            return self.server_id._is_oauth_auth_enabled()
        return self.server_id._is_bearer_auth_enabled()

    @tools.ormcache("key", "security_key")
    def _get_mcp_server_by_key(self, key, security_key):
        server_key_id, expiration_date = super()._get_mcp_server_by_key(
            key, security_key
        )
        if not server_key_id:
            return server_key_id, expiration_date
        server_key = self.sudo().browse(server_key_id)
        if not server_key._is_enabled_by_server():
            return False, False
        return server_key_id, expiration_date
