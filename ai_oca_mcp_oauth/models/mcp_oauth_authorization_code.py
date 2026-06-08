# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import secrets
from hmac import compare_digest

from odoo import api, fields, models


class McpOauthAuthorizationCode(models.Model):
    _name = "mcp.oauth.authorization.code"
    _description = "MCP OAuth Authorization Code"

    code_hash = fields.Char(required=True, copy=False, index=True)
    server_id = fields.Many2one("mcp.server", required=True, ondelete="cascade")
    client_id = fields.Many2one("mcp.oauth.client", required=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    redirect_uri = fields.Char(required=True)
    scope = fields.Char()
    code_challenge = fields.Char(required=True)
    code_challenge_method = fields.Selection([("S256", "S256")], required=True)
    expiration_date = fields.Datetime(required=True)
    used = fields.Boolean(default=False)

    @api.model
    def _hash_code(self, code):
        return hashlib.sha256(code.encode()).hexdigest()

    @api.model
    def _create_code(
        self,
        server,
        client,
        user,
        redirect_uri,
        scope,
        code_challenge,
        code_challenge_method,
    ):
        code = secrets.token_urlsafe(32)
        self.sudo().create(
            {
                "code_hash": self._hash_code(code),
                "server_id": server.id,
                "client_id": client.id,
                "user_id": user.id,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "expiration_date": fields.Datetime.add(
                    fields.Datetime.now(), minutes=10
                ),
            }
        )
        return code

    @api.model
    def _consume_code(self, server, client, code, redirect_uri, code_verifier):
        record = self.sudo().search(
            [
                ("code_hash", "=", self._hash_code(code)),
                ("server_id", "=", server.id),
                ("client_id", "=", client.id),
                ("redirect_uri", "=", redirect_uri),
            ],
            limit=1,
        )
        if not record or record.used:
            return False, "invalid_grant"
        if record.expiration_date < fields.Datetime.now():
            return False, "invalid_grant"
        if not record._check_code_verifier(code_verifier):
            return False, "invalid_grant"
        record.used = True
        return record, False

    def _check_code_verifier(self, code_verifier):
        self.ensure_one()
        if not code_verifier:
            return False
        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return compare_digest(challenge, self.code_challenge)
