import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from markupsafe import escape

from odoo import fields, http
from odoo.addons.ai_oca_mcp.controllers.mcp_controller import (
    McpController as BaseMcpController,
)
from odoo.exceptions import ValidationError
from odoo.http import request


class McpOauthController(BaseMcpController):
    _oauth_scope = "mcp.tools.read mcp.tools.call"

    @http.route(
        "/mcp/<string:key>", type="http", auth="none", methods=["POST"], csrf=False
    )
    def mcp_endpoint(self, key, **kwargs):
        match = re.match(
            r"Bearer\s+(.+)", request.httprequest.headers.get("Authorization", "")
        )
        payload = self._json_payload()
        if not match:
            return self._mcp_auth_failed(key, payload, status=401)
        security_key = match.group(1).strip()
        server_id, expiration_date = (
            request.env["mcp.server.key"]
            .sudo()
            ._get_mcp_server_by_key(key, security_key)
        )
        if expiration_date and expiration_date < fields.Datetime.now():
            request.env["mcp.server.key"].sudo().browse(server_id).expire_key()
            server_id = False
        if not server_id:
            return self._mcp_auth_failed(key, payload)
        server = request.env["mcp.server.key"].sudo().browse(server_id)
        server = server.with_user(server.user_id.id)
        method = payload.get("method")
        if method == "initialize":
            return request.make_json_response(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "odoo-mcp", "version": "0.1.0"},
                    },
                }
            )

        if method == "tools/list":
            return request.make_json_response(server._tools_list(payload))

        if method == "tools/call":
            return request.make_json_response(server._tools_call(payload))

        return request.make_json_response(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {"code": -32601, "message": "Method not found"},
            }
        )

    @http.route(
        "/.well-known/oauth-protected-resource/mcp/<string:key>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def oauth_protected_resource_metadata(self, key, **kwargs):
        server = self._get_mcp_server(key)
        if not server or not server._is_oauth_auth_enabled():
            return request.not_found()
        return request.make_json_response(
            {
                "resource": server.url,
                "authorization_servers": [self._oauth_issuer_url(server)],
                "scopes_supported": self._oauth_scope.split(),
                "bearer_methods_supported": ["header"],
            }
        )

    @http.route(
        [
            "/.well-known/oauth-authorization-server/mcp/oauth/<string:key>",
            "/mcp/oauth/<string:key>/.well-known/oauth-authorization-server",
        ],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def oauth_authorization_server_metadata(self, key, **kwargs):
        server = self._get_mcp_server(key)
        if not server or not server._is_oauth_auth_enabled():
            return request.not_found()
        issuer = self._oauth_issuer_url(server)
        return request.make_json_response(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "registration_endpoint": f"{issuer}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": self._oauth_scope.split(),
            }
        )

    @http.route(
        "/mcp/oauth/<string:key>/register",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def oauth_register(self, key, **kwargs):
        server = self._get_mcp_server(key)
        if not server or not server._is_oauth_auth_enabled():
            return request.not_found()
        try:
            client = request.env["mcp.oauth.client"]._register_from_payload(
                server, self._json_payload()
            )
        except ValidationError as error:
            return self._oauth_error("invalid_request", str(error), status=400)
        return request.make_json_response(client._registration_response(), status=201)

    @http.route(
        "/mcp/oauth/<string:key>/authorize",
        type="http",
        auth="user",
        methods=["GET", "POST"],
    )
    def oauth_authorize(self, key, **kwargs):
        server = self._get_mcp_server(key)
        if not server or not server._is_oauth_auth_enabled():
            return request.not_found()

        params = (
            request.httprequest.form
            if request.httprequest.method == "POST"
            else request.httprequest.args
        )
        client = self._get_oauth_client(server, params.get("client_id"))
        redirect_uri = params.get("redirect_uri")
        state = params.get("state")
        error = self._validate_authorization_request(server, client, params)
        if error:
            if redirect_uri and client and client._check_redirect_uri(redirect_uri):
                return request.redirect(
                    self._append_query(redirect_uri, {"error": error, "state": state}),
                    local=False,
                )
            return self._oauth_error(error, status=400)

        if request.httprequest.method == "GET":
            return self._oauth_consent_response(server, client, params)
        if params.get("decision") != "approve":
            return request.redirect(
                self._append_query(
                    redirect_uri, {"error": "access_denied", "state": state}
                ),
                local=False,
            )
        user = self._oauth_password_user(params)
        if not user:
            return self._oauth_consent_response(
                server,
                client,
                params,
                error="Enter valid Odoo credentials to authorize this MCP client.",
            )

        code = request.env["mcp.oauth.authorization.code"]._create_code(
            server=server,
            client=client,
            user=user,
            redirect_uri=redirect_uri,
            scope=params.get("scope") or self._oauth_scope,
            code_challenge=params.get("code_challenge"),
            code_challenge_method=params.get("code_challenge_method"),
        )
        return request.redirect(
            self._append_query(redirect_uri, {"code": code, "state": state}),
            local=False,
        )

    @http.route(
        "/mcp/oauth/<string:key>/token",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def oauth_token(self, key, **kwargs):
        server = self._get_mcp_server(key)
        if not server or not server._is_oauth_auth_enabled():
            return request.not_found()

        params = self._request_params()
        grant_type = params.get("grant_type")
        if grant_type == "authorization_code":
            return self._oauth_authorization_code_token(server, params)
        if grant_type == "refresh_token":
            return self._oauth_refresh_token(server, params)
        return self._oauth_error("unsupported_grant_type", status=400)

    def _oauth_authorization_code_token(self, server, params):
        client = self._get_oauth_client(server, params.get("client_id"))
        if not client:
            return self._oauth_error("invalid_client", status=401)
        code_record, error = request.env["mcp.oauth.authorization.code"]._consume_code(
            server=server,
            client=client,
            code=params.get("code"),
            redirect_uri=params.get("redirect_uri"),
            code_verifier=params.get("code_verifier"),
        )
        if error:
            return self._oauth_error(error, status=400)
        return self._issue_oauth_token(
            server=server,
            client=client,
            user=code_record.user_id,
            scope=code_record.scope,
        )

    def _oauth_refresh_token(self, server, params):
        client = self._get_oauth_client(server, params.get("client_id"))
        if not client:
            return self._oauth_error("invalid_client", status=401)
        refresh_token = params.get("refresh_token")
        key_model = request.env["mcp.server.key"].sudo()
        server_key = key_model.search(
            [
                ("server_id", "=", server.id),
                ("oauth_client_id", "=", client.id),
                ("auth_type", "=", "oauth"),
                ("refresh_token_hash", "=", key_model._hash_key(refresh_token or "")),
                ("state", "=", "active"),
            ],
            limit=1,
        )
        if not server_key:
            return self._oauth_error("invalid_grant", status=400)
        return self._issue_oauth_token(
            server=server,
            client=client,
            user=server_key.user_id,
            scope=server_key.scope,
            server_key=server_key,
        )

    def _issue_oauth_token(self, server, client, user, scope, server_key=False):
        key_model = request.env["mcp.server.key"].sudo()
        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)
        expires_in = 3600
        vals = {
            "name": f"OAuth - {client.name} - {user.name}",
            "server_id": server.id,
            "auth_type": "oauth",
            "hashed_key": key_model._hash_key(access_token),
            "refresh_token_hash": key_model._hash_key(refresh_token),
            "oauth_client_id": client.id,
            "scope": scope or self._oauth_scope,
            "user_id": user.id,
            "expiration_date": fields.Datetime.add(
                fields.Datetime.now(), seconds=expires_in
            ),
            "state": "active",
        }
        if server_key:
            server_key.write(vals)
            key_model._clear_mcp_server_by_key_cache()
        else:
            key_model.create(vals)
        return request.make_json_response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "refresh_token": refresh_token,
                "scope": scope or self._oauth_scope,
            }
        )

    def _mcp_auth_failed(self, key, payload, status=None):
        server = self._get_mcp_server(key)
        headers = None
        if server and server._is_oauth_auth_enabled():
            status = 401
            headers = [
                (
                    "WWW-Authenticate",
                    (
                        'Bearer resource_metadata="%s", scope="%s"'
                        % (server.oauth_resource_metadata_url, self._oauth_scope)
                    ),
                )
            ]
        status = status or 200
        return request.make_json_response(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {"code": -32000, "message": "Connection failed"},
            },
            status=status,
            headers=headers,
        )

    def _get_mcp_server(self, key):
        return (
            request.env["mcp.server"]
            .sudo()
            .search([("key", "=", key), ("active", "=", True)], limit=1)
        )

    def _get_oauth_client(self, server, client_id):
        if not client_id:
            return request.env["mcp.oauth.client"].sudo()
        return (
            request.env["mcp.oauth.client"]
            .sudo()
            .search(
                [
                    ("server_id", "=", server.id),
                    ("client_id", "=", client_id),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )

    def _validate_authorization_request(self, server, client, params):
        if params.get("response_type") != "code":
            return "unsupported_response_type"
        if not client:
            return "invalid_client"
        if not client._check_redirect_uri(params.get("redirect_uri")):
            return "invalid_request"
        if params.get("code_challenge_method") != "S256":
            return "invalid_request"
        if not params.get("code_challenge"):
            return "invalid_request"
        resource = params.get("resource")
        if resource and resource != server.url:
            return "invalid_target"
        return False

    def _request_params(self):
        if request.httprequest.mimetype == "application/json":
            return self._json_payload()
        return request.httprequest.form.to_dict(flat=True)

    def _json_payload(self):
        data = request.httprequest.data.decode("utf-8")
        if not data:
            return {}
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}

    def _oauth_error(self, error, description=None, status=400):
        payload = {"error": error}
        if description:
            payload["error_description"] = description
        return request.make_json_response(payload, status=status)

    def _oauth_issuer_url(self, server):
        base_url = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url")
            .rstrip("/")
        )
        return f"{base_url}/mcp/oauth/{server.key}"

    def _oauth_password_user(self, params):
        login = (params.get("mcp_login") or "").strip()
        password = params.get("mcp_password") or ""
        if not login or not password:
            return False
        try:
            user = (
                request.env["res.users"]
                .sudo()
                .search([("login", "=", login)], limit=1)
            )
            if not user:
                return False
            credential = {"login": login, "password": password, "type": "password"}
            try:
                user.with_user(user)._check_credentials(
                    credential,
                    {"interactive": True},
                )
            except TypeError:
                user.with_user(user)._check_credentials(password, {"interactive": True})
        except Exception:
            return False
        return user

    def _oauth_consent_response(self, server, client, params, error=None):
        fields = {
            name: params.get(name)
            for name in (
                "response_type",
                "client_id",
                "redirect_uri",
                "scope",
                "state",
                "code_challenge",
                "code_challenge_method",
                "resource",
            )
            if params.get(name)
        }
        hidden_fields = "\n".join(
            '<input type="hidden" name="%s" value="%s" />'
            % (escape(name), escape(value))
            for name, value in fields.items()
        )
        html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Authorize MCP Client</title>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        background: #f8f9fa;
        color: #1f2933;
      }
      main {
        max-width: 520px;
        margin: 12vh auto;
        padding: 32px;
        background: white;
        border: 1px solid #d8dde3;
        border-radius: 8px;
      }
      h1 {
        margin: 0 0 16px;
        font-size: 24px;
      }
      p {
        line-height: 1.5;
      }
      label {
        display: block;
        font-weight: 600;
        margin: 16px 0 6px;
      }
      input {
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        box-sizing: border-box;
        font-size: 14px;
        padding: 10px 12px;
        width: 100%%;
      }
      .error {
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 4px;
        color: #991b1b;
        padding: 10px 12px;
      }
      .actions {
        display: flex;
        gap: 12px;
        margin-top: 24px;
      }
      button {
        border: 1px solid #714b67;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
        padding: 10px 16px;
      }
      button[value="approve"] {
        background: #714b67;
        color: white;
      }
      button[value="deny"] {
        background: white;
        color: #714b67;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Authorize MCP Client</h1>
      <p>
        %(client_name)s wants to access %(server_name)s.
      </p>
      %(error)s
      <form method="post">
        <input type="hidden" name="csrf_token" value="%(csrf_token)s" />
        %(hidden_fields)s
        <label for="mcp_login">Odoo user</label>
        <input
          id="mcp_login"
          name="mcp_login"
          autocomplete="username"
          value="%(login)s"
          required
        />
        <label for="mcp_password">Odoo password</label>
        <input
          id="mcp_password"
          name="mcp_password"
          type="password"
          autocomplete="current-password"
          required
        />
        <div class="actions">
          <button type="submit" name="decision" value="approve">Authorize</button>
          <button type="submit" name="decision" value="deny" formnovalidate>
            Cancel
          </button>
        </div>
      </form>
    </main>
  </body>
</html>
        """ % {
            "client_name": escape(client.name),
            "server_name": escape(server.name or server.key),
            "error": (
                '<p class="error">%s</p>' % escape(error)
                if error
                else ""
            ),
            "login": escape(params.get("mcp_login") or request.env.user.login or ""),
            "csrf_token": escape(request.csrf_token()),
            "hidden_fields": hidden_fields,
        }
        return request.make_response(
            html,
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )

    def _append_query(self, url, params):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({key: value for key, value in params.items() if value})
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )
