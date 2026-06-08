# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import json
from urllib.parse import urlencode

from odoo.tests.common import HttpCase
from odoo.tools import mute_logger


class TestMcpOauth(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mcp.server"].create(
            {
                "name": "Test Server",
                "auth_type": "oauth",
                "tool_ids": [(4, cls.env.ref("ai_tool.current_date").id)],
            }
        )

    @mute_logger("odoo.http")
    def test_oauth_authentication_challenge(self):
        request = self.url_open(
            f"/mcp/{self.server.key}",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "initialize",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(request.status_code, 401)
        self.assertIn("WWW-Authenticate", request.headers)
        self.assertIn("resource_metadata", request.headers["WWW-Authenticate"])

    def test_oauth_discovery(self):
        request = self.url_open(
            f"/.well-known/oauth-protected-resource/mcp/{self.server.key}"
        )
        self.assertEqual(request.status_code, 200)
        response = json.loads(request.content.decode("utf-8"))
        self.assertEqual(self.server.url, response["resource"])
        self.assertIn("authorization_servers", response)

        request = self.url_open(
            f"/.well-known/oauth-authorization-server/mcp/oauth/{self.server.key}"
        )
        self.assertEqual(request.status_code, 200)
        response = json.loads(request.content.decode("utf-8"))
        self.assertIn("authorization_endpoint", response)
        self.assertIn("token_endpoint", response)
        self.assertIn("registration_endpoint", response)
        self.assertIn("S256", response["code_challenge_methods_supported"])

    def test_oauth_register(self):
        request = self.url_open(
            f"/mcp/oauth/{self.server.key}/register",
            data=json.dumps(
                {
                    "client_name": "Claude",
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(request.status_code, 201)
        response = json.loads(request.content.decode("utf-8"))
        self.assertIn("client_id", response)
        self.assertEqual("none", response["token_endpoint_auth_method"])

    def test_oauth_key_wizard_keeps_auth_type(self):
        wizard = (
            self.env["mcp.server.key.add"]
            .with_context(
                default_server_id=self.server.id,
                default_auth_type="oauth",
            )
            .create({"name": "OAuth Key"})
        )
        self.assertEqual("oauth", wizard.auth_type)
        wizard.generate_key()
        self.assertEqual("oauth", wizard.auth_type)
        self.assertEqual("oauth", wizard.key_id.auth_type)

    def test_bearer_oauth_key_wizard_can_generate_oauth_key(self):
        server = self.env["mcp.server"].create(
            {
                "name": "Mixed Auth Server",
                "auth_type": "bearer_oauth",
            }
        )
        wizard = (
            self.env["mcp.server.key.add"]
            .with_context(default_server_id=server.id)
            .create({"name": "OAuth Key"})
        )
        self.assertEqual("bearer", wizard.auth_type)
        wizard.auth_type = "oauth"
        wizard.generate_key()
        self.assertEqual("oauth", wizard.key_id.auth_type)

    def test_oauth_token_and_refresh(self):
        client = self.env["mcp.oauth.client"].create(
            {
                "name": "Claude",
                "server_id": self.server.id,
                "redirect_uris": json.dumps(["https://claude.ai/callback"]),
            }
        )
        code_verifier = "test-verifier"
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        code = self.env["mcp.oauth.authorization.code"]._create_code(
            server=self.server,
            client=client,
            user=self.env.user,
            redirect_uri="https://claude.ai/callback",
            scope="mcp.tools.read mcp.tools.call",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        request = self.url_open(
            f"/mcp/oauth/{self.server.key}/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": client.client_id,
                    "redirect_uri": "https://claude.ai/callback",
                    "code": code,
                    "code_verifier": code_verifier,
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(request.status_code, 200)
        response = json.loads(request.content.decode("utf-8"))
        self.assertIn("access_token", response)
        self.assertIn("refresh_token", response)

        request = self.url_open(
            f"/mcp/{self.server.key}",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "initialize",
                }
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {response['access_token']}",
            },
        )
        self.assertEqual(request.status_code, 200)
        response_mcp = json.loads(request.content.decode("utf-8"))
        self.assertIn("result", response_mcp)

        request = self.url_open(
            f"/mcp/oauth/{self.server.key}/token",
            data=urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": client.client_id,
                    "refresh_token": response["refresh_token"],
                }
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(request.status_code, 200)
        response = json.loads(request.content.decode("utf-8"))
        self.assertIn("access_token", response)
