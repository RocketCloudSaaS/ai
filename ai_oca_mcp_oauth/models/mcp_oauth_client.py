# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class McpOauthClient(models.Model):
    _name = "mcp.oauth.client"
    _description = "MCP OAuth Client"

    name = fields.Char(required=True)
    server_id = fields.Many2one("mcp.server", required=True, ondelete="cascade")
    client_id = fields.Char(
        required=True,
        copy=False,
        index=True,
        default=lambda self: secrets.token_urlsafe(24),
    )
    redirect_uris = fields.Text(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("client_id_uniq", "unique(client_id)", "The OAuth client ID must be unique"),
    ]

    def _get_redirect_uris(self):
        self.ensure_one()
        try:
            uris = json.loads(self.redirect_uris or "[]")
        except json.JSONDecodeError:
            uris = []
        return uris if isinstance(uris, list) else []

    def _check_redirect_uri(self, redirect_uri):
        self.ensure_one()
        return redirect_uri in self._get_redirect_uris()

    @api.model
    def _register_from_payload(self, server, payload):
        redirect_uris = payload.get("redirect_uris") or []
        if not redirect_uris or not isinstance(redirect_uris, list):
            raise ValidationError(_("redirect_uris is required"))
        client_name = payload.get("client_name") or payload.get("name") or "MCP Client"
        return self.sudo().create(
            {
                "name": client_name,
                "server_id": server.id,
                "redirect_uris": json.dumps(redirect_uris),
            }
        )

    def _registration_response(self):
        self.ensure_one()
        return {
            "client_id": self.client_id,
            "client_id_issued_at": int(self.create_date.timestamp()),
            "client_name": self.name,
            "redirect_uris": self._get_redirect_uris(),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": "mcp.tools.read mcp.tools.call",
        }
