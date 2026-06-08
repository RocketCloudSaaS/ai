import base64

import requests

from odoo import fields, models, tools


class AiApiConnection(models.Model):
    _name = "ai.api.connection"
    _description = "API Connection"

    name = fields.Char(required=True, help="Internal name to reference this connection")
    base_url = fields.Char(
        required=True,
        help="Base URL of the API (e.g. https://api.example.com)",
    )
    description = fields.Text()
    default_endpoint = fields.Char(
        help=(
            "Default endpoint path to use when the AI omits an endpoint or sends '/' "
            "(e.g. /v1/opencode/query)."
        ),
    )
    default_method = fields.Selection(
        [
            ("GET", "GET"),
            ("POST", "POST"),
            ("PUT", "PUT"),
            ("PATCH", "PATCH"),
            ("DELETE", "DELETE"),
        ],
        default="GET",
        required=True,
        help="Default HTTP method for this connection.",
    )
    default_body = fields.Json(
        string="Default Body",
        help="JSON object merged into every request body before the AI-provided body.",
    )
    auth_type = fields.Selection(
        [
            ("none", "None"),
            ("bearer", "Bearer Token"),
            ("basic", "Basic Auth"),
            ("api_key", "API Key"),
        ],
        default="none",
        required=True,
    )
    auth_value = fields.Char(
        help="Bearer token, password, or API key value depending on auth type"
    )
    auth_header_name = fields.Char(
        default="X-API-Key",
        help="Header name used when auth type is 'API Key'",
    )
    default_headers = fields.Json(
        string="Default Headers",
        help="Additional headers sent with every request (key-value pairs)",
    )
    default_timeout = fields.Integer(
        default=30,
        help="Default timeout in seconds for requests",
    )
    active = fields.Boolean(default=True)

    def _build_request_args(
        self,
        endpoint="",
        method="GET",
        headers=None,
        body=None,
        query_params=None,
        timeout=None,
    ):
        self.ensure_one()

        requested_endpoint = (endpoint or "").strip()
        use_default_endpoint = bool(
            self.default_endpoint and requested_endpoint in ("", "/")
        )
        endpoint = self.default_endpoint if use_default_endpoint else requested_endpoint

        method = (method or "").upper()
        if self.default_method and (
            not method
            or use_default_endpoint
            or (
                self.default_endpoint
                and endpoint.lstrip("/") == self.default_endpoint.lstrip("/")
                and method == "GET"
                and self.default_method != "GET"
            )
        ):
            method = self.default_method

        if isinstance(self.default_body, dict) and isinstance(body, dict):
            body = {**self.default_body, **body}
        elif isinstance(self.default_body, dict) and body is None:
            body = dict(self.default_body)
        body = self._prepare_body(body, endpoint=endpoint)

        url = self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        req_headers = {}

        auth_type = self.auth_type
        if auth_type == "bearer":
            req_headers["Authorization"] = f"Bearer {self.auth_value}"
        elif auth_type == "basic":
            encoded = base64.b64encode(self.auth_value.encode()).decode()
            req_headers["Authorization"] = f"Basic {encoded}"
        elif auth_type == "api_key":
            header_name = self.auth_header_name or "X-API-Key"
            req_headers[header_name] = self.auth_value or ""

        if self.default_headers:
            req_headers.update(self.default_headers)
        if headers:
            req_headers.update(headers)

        return {
            "url": url,
            "method": method,
            "headers": req_headers,
            "json": body,
            "params": query_params,
            "timeout": timeout or self.default_timeout or 30,
        }

    def _prepare_body(self, body, endpoint=""):
        if not isinstance(body, dict):
            return body
        mode = str(body.get("mode") or "").strip().lower()
        endpoint_path = "/" + str(endpoint or "").strip().lstrip("/")
        is_opencode_query = endpoint_path.rstrip("/") == "/v1/opencode/query"
        if mode not in {"chatter", "bridge", "odoo_chatter"} and not is_opencode_query:
            return body
        if isinstance(body.get("message"), dict) and isinstance(body.get("_odoo"), dict):
            return body
        return self._with_odoo_chatter_context(body)

    def _with_odoo_chatter_context(self, body):
        user = self.env.user
        partner = user.partner_id
        message_text = (
            body.get("query")
            or body.get("question")
            or body.get("prompt")
            or body.get("message")
            or ""
        )
        thread = body.get("thread") if isinstance(body.get("thread"), dict) else {}
        thread_model = (
            thread.get("model") or body.get("thread_model") or "res.users"
        )
        thread_res_id = (
            thread.get("res_id") or body.get("thread_res_id") or user.id
        )
        IrParamSudo = self.env["ir.config_parameter"].sudo()
        dbuuid = IrParamSudo.get_param("database.uuid")
        db_create_date = IrParamSudo.get_param("database.create_date")
        result = dict(body)
        result.setdefault("action", "opencode_query")
        result["mode"] = "chatter"
        result["message"] = {
            "res_id": int(thread_res_id or 0),
            "model": str(thread_model or "res.users"),
            "body": str(message_text or ""),
            "author_id": partner.id,
            "subject": "",
            "date": fields.Datetime.now().isoformat(),
            "author_name": partner.name,
            "attachment_ids": [],
            "parent_id": False,
        }
        result["_odoo"] = {
            "db": dbuuid,
            "db_name": self.env.cr.dbname,
            "db_hash": tools.hmac(
                self.env(su=True),
                "database-hash",
                (dbuuid, db_create_date, self.env.cr.dbname),
            ),
            "user_id": user.id,
            "company_id": user.company_id.id,
        }
        result["_copilot"] = {
            "user_id": user.id,
            "user_name": user.name,
            "lang": user.lang or self.env.context.get("lang") or "en_US",
            "tz": user.tz or self.env.context.get("tz") or "UTC",
            "company_id": user.company_id.id,
            "partner": {
                "id": partner.id,
                "name": partner.name,
            },
        }
        return result

    def execute_request(
        self,
        endpoint="",
        method="GET",
        headers=None,
        body=None,
        query_params=None,
        timeout=None,
    ):
        args = self._build_request_args(
            endpoint=endpoint,
            method=method,
            headers=headers,
            body=body,
            query_params=query_params,
            timeout=timeout,
        )
        response = requests.request(
            method=args["method"],
            url=args["url"],
            headers=args["headers"],
            json=args["json"],
            params=args["params"],
            timeout=args["timeout"],
        )
        try:
            response_body = response.json()
        except Exception:
            response_body = None
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body,
            "text": response.text,
        }
