AI Connections OpenCode
=======================

This module creates the default ``opencode-connector`` API connection for the
OpenCode/Odoo Copilot gateway.

The connection uses ``http://127.0.0.1:8000`` with the default endpoint
``/v1/opencode/query`` and the ``POST`` method.

The Bearer token is read during module installation from
``/etc/odoo-copilot/copilot.env`` using the ``COPILOT_BRIDGE_TOKEN`` variable.
