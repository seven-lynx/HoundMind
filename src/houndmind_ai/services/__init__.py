"""The control plane: one process, one port, one authenticated API (D7).

Importing this package deliberately pulls in nothing heavy. `aiohttp` is imported inside
:mod:`houndmind_ai.services.module` when the plane actually starts, so a runtime with
`modules.api.enabled: false` never pays for it, and `import houndmind_ai.services` stays usable
on a machine without the package installed.
"""

from __future__ import annotations

from houndmind_ai.services.settings import DEFAULT_HOST, DEFAULT_PORT, ApiSettings

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "ApiSettings"]