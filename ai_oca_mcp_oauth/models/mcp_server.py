# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class McpServer(models.Model):
    _inherit = "mcp.server"

    auth_type = fields.Selection(
        [
            ("bearer", "Bearer Token"),
            ("oauth", "OAuth 2.0"),
            ("bearer_oauth", "Bearer Token and OAuth 2.0"),
        ],
        default="bearer",
        required=True,
    )
    oauth_resource_metadata_url = fields.Char(
        compute="_compute_url",
        groups="base.group_system",
    )
    oauth_authorization_server_url = fields.Char(
        compute="_compute_url",
        groups="base.group_system",
    )

    def _compute_url(self):
        super()._compute_url()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for record in self:
            record.oauth_resource_metadata_url = (
                f"{base_url}/.well-known/oauth-protected-resource/mcp/{record.key}"
            )
            record.oauth_authorization_server_url = (
                f"{base_url}/.well-known/oauth-authorization-server/mcp/oauth/"
                f"{record.key}"
            )

    def _is_bearer_auth_enabled(self):
        self.ensure_one()
        return self.auth_type in ("bearer", "bearer_oauth")

    def _is_oauth_auth_enabled(self):
        self.ensure_one()
        return self.auth_type in ("oauth", "bearer_oauth")
