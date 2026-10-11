"""radicale_agents_store: Radicale storage plugin over the agents-store
canonical layer.

GPLv3 boundary: this package is the only place the store talks to
Radicale (vobject internals included). Core stays MIT + stdlib-only.
"""
from .storage import Collection, Storage

__all__ = ["Collection", "Storage"]
