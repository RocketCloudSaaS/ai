# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from pathlib import Path

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

COPILOT_ENV_PATH = Path("/etc/odoo-copilot/copilot.env")
COPILOT_TOKEN_KEY = "COPILOT_BRIDGE_TOKEN"
OPENCODE_CONNECTION_XMLID = "ai_connections_opencode.opencode_connector"


def post_init_hook(env_or_cr):
    env = _hook_env(env_or_cr)
    connection = _get_or_create_opencode_connection(env)
    token = _read_copilot_bridge_token()
    if token:
        connection.auth_value = token
    else:
        _logger.warning(
            "%s was not found in %s. The opencode-connector connection was created "
            "without an Auth Value.",
            COPILOT_TOKEN_KEY,
            COPILOT_ENV_PATH,
        )


def _hook_env(env_or_cr):
    if hasattr(env_or_cr, "env"):
        return env_or_cr.env
    if hasattr(env_or_cr, "cr"):
        return env_or_cr
    return api.Environment(env_or_cr, SUPERUSER_ID, {})


def _get_or_create_opencode_connection(env):
    values = _opencode_connection_values()
    xmlid = env.ref(OPENCODE_CONNECTION_XMLID, raise_if_not_found=False)
    if xmlid:
        xmlid.write(values)
        return xmlid

    connection = env["ai.api.connection"].sudo().search(
        [("name", "=", values["name"])],
        limit=1,
    )
    if connection:
        connection.write(values)
    else:
        connection = env["ai.api.connection"].sudo().create(values)
    _create_connection_xmlid(env, connection)
    return connection


def _opencode_connection_values():
    return {
        "name": "opencode-connector",
        "base_url": "http://127.0.0.1:8000",
        "description": (
            "A tool designed to manage and view any information, process or action "
            "related to Odoo."
        ),
        "default_endpoint": "/v1/opencode/query",
        "default_method": "POST",
        "auth_type": "bearer",
        "default_timeout": 60,
        "active": True,
    }


def _create_connection_xmlid(env, connection):
    env["ir.model.data"].sudo().create(
        {
            "module": "ai_connections_opencode",
            "name": "opencode_connector",
            "model": "ai.api.connection",
            "res_id": connection.id,
            "noupdate": True,
        }
    )


def _read_copilot_bridge_token():
    if not COPILOT_ENV_PATH.is_file():
        return ""
    for raw_line in COPILOT_ENV_PATH.read_text(encoding="utf-8").splitlines():
        value = _parse_env_value(raw_line, COPILOT_TOKEN_KEY)
        if value is not None:
            return value
    return ""


def _parse_env_value(raw_line, key):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    prefix = f"{key}="
    if not line.startswith(prefix):
        return None
    value = line[len(prefix) :].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value
