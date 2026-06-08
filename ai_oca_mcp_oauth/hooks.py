# Copyright 2026 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import SUPERUSER_ID, api


def post_init_hook(env_or_cr, registry=None):
    if registry:
        env = api.Environment(env_or_cr, SUPERUSER_ID, {})
    else:
        env = env_or_cr
    env["mcp.server"].search([("auth_type", "=", False)]).write(
        {"auth_type": "bearer"}
    )
    env["mcp.server.key"].search([("auth_type", "=", False)]).write(
        {"auth_type": "bearer"}
    )
