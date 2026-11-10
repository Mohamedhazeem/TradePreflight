"""TradePreflight — deterministic execution firewall for AI-initiated orders.

The package is deliberately layered:

- ``domain``   — pure value objects and policy schema
- ``adapters`` — broker-specific argument translation
- ``services`` — policy loading, rule evaluation, audit persistence
- ``tools``    — Hermes tool schemas and handlers
- ``hooks``    — Hermes lifecycle wiring and fail-closed enforcement
"""

from __future__ import annotations

__version__ = "0.1.0"

#: Canonical plugin id. Used for ``plugin_db`` / ``plugin_data_dir`` and in
#: manifests. Keep it in sync with ``plugin.yaml``.
PLUGIN_NAME = "trade-preflight"

__all__ = ["PLUGIN_NAME", "__version__"]
