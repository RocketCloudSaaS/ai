# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from copy import deepcopy
from urllib.parse import urlparse

import requests

from odoo import models

from odoo.addons.ai_tool.tools import aitool


class AiTool(models.Model):
    _inherit = "ai.tool"

    def _get_tool_definition(self):
        self.ensure_one()
        definition = super()._get_tool_definition()
        if self.function_name != "_ai_api_request":
            return definition
        return self._get_api_request_tool_definition(definition)

    def _get_api_request_tool_definition(self, definition):
        definition = deepcopy(definition)
        connections = self.env["ai.api.connection"].sudo().search(
            [("active", "=", True)], order="name"
        )
        if not connections:
            return definition

        catalog, connection_names = self._get_api_connection_catalog(connections)

        catalog_text = "\n".join(catalog)
        definition["description"] = "%s\n\nConfigured connections:\n%s\n\n%s" % (
            definition.get("description") or "",
            catalog_text,
            (
                "Prefer connection_name when one of these connections matches the "
                "request. Direct URLs are not exposed while configured connections "
                "are available. Do not call the MCP server URL through this tool."
            ),
        )
        properties = definition["inputSchema"]["properties"]
        properties["connection_name"]["enum"] = connection_names
        properties["connection_name"]["description"] = (
            "Name of a configured ai.api.connection to use. Available connections:\n"
            f"{catalog_text}"
        )
        properties["method"]["description"] = (
            "HTTP method. Use the connection default method when listed in the "
            "connection catalog."
        )
        properties["endpoint"]["description"] = (
            "Endpoint path relative to the connection base_url. Use the exact default "
            "endpoint shown in the connection catalog when one is listed; do not use "
            "'/' unless the catalog explicitly says it is valid."
        )
        properties.pop("url", None)
        definition["inputSchema"]["required"] = ["connection_name", "endpoint", "method"]
        return definition

    def _get_api_connection_catalog(self, connections):
        catalog = []
        connection_names = []
        for connection in connections:
            connection_names.append(connection.name)
            details = []
            description = (connection.description or "").strip()
            if description:
                details.append(description)
            if connection.default_endpoint:
                details.append(
                    "Default request: %s %s"
                    % (connection.default_method or "GET", connection.default_endpoint)
                )
            if connection.default_body:
                details.append(f"Default body: {connection.default_body}")
            if details:
                catalog.append(f"- {connection.name}: {'; '.join(details)}")
            else:
                catalog.append(f"- {connection.name}")
        return catalog, connection_names

    def _api_connection_direct_url_error(self, url):
        connections = self.env["ai.api.connection"].sudo().search(
            [("active", "=", True)], order="name"
        )
        if not connections:
            return False
        catalog, connection_names = self._get_api_connection_catalog(connections)
        parsed = urlparse(url or "")
        if parsed.path.startswith("/mcp/") or connection_names:
            return (
                "Direct URL calls are disabled for api_request while configured "
                "API connections are available. Use connection_name instead. "
                "Available connections:\n%s"
            ) % "\n".join(catalog)
        return False

    @aitool(
        input_schema={
            "url": {
                "type": "string",
                "description": (
                    "Full URL of the API endpoint "
                    "(not needed if connection_name is provided)"
                ),
            },
            "method": {
                "type": "string",
                "description": "HTTP method",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            },
            "headers": {
                "type": "object",
                "description": (
                    "HTTP headers as key-value pairs "
                    "(merged with connection defaults)"
                ),
            },
            "body": {
                "type": "object",
                "description": "Request body as JSON object",
            },
            "query_params": {
                "type": "object",
                "description": "Query parameters as key-value pairs",
            },
            "timeout": {
                "type": "number",
                "description": "Request timeout in seconds",
            },
            "connection_name": {
                "type": "string",
                "description": (
                    "Name of a configured ai.api.connection to use "
                    "(uses its base_url, auth, and default headers)"
                ),
            },
            "endpoint": {
                "type": "string",
                "description": (
                    "Endpoint path relative to the connection base_url "
                    "(only used with connection_name)"
                ),
            },
        },
        required_inputs=[],
        output_schema={
            "status_code": {"type": "integer"},
            "headers": {"type": "object"},
            "body": {"type": "object"},
            "text": {"type": "string"},
        },
    )
    def _ai_api_request(
        self,
        url=None,
        method="GET",
        headers=None,
        body=None,
        query_params=None,
        timeout=None,
        connection_name=None,
        endpoint="",
    ):
        if connection_name:
            connection = self.env["ai.api.connection"].search(
                [("name", "=", connection_name)], limit=1
            )
            if not connection:
                return {
                    "status_code": 0,
                    "headers": {},
                    "body": None,
                    "text": f"Connection '{connection_name}' not found",
                }
            return connection.execute_request(
                endpoint=endpoint,
                method=method,
                headers=headers,
                body=body,
                query_params=query_params,
                timeout=timeout,
            )
        if not url:
            return {
                "status_code": 0,
                "headers": {},
                "body": None,
                "text": "Either 'url' or 'connection_name' must be provided",
            }
        direct_url_error = self._api_connection_direct_url_error(url)
        if direct_url_error:
            return {
                "status_code": 0,
                "headers": {},
                "body": None,
                "text": direct_url_error,
            }
        req_headers = headers or {}
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=req_headers,
                json=body,
                params=query_params,
                timeout=timeout or 30,
            )
        except Exception as e:
            return {
                "status_code": 0,
                "headers": {},
                "body": None,
                "text": str(e),
            }
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
