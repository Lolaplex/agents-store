"""Extension point: wrappers and capabilities register here, in-process or via entry points.

Entry-point groups (pyproject of an extension package):
    [project.entry-points."agents_store.wrappers"]      name = "pkg.module:factory"
    [project.entry-points."agents_store.capabilities"]  name = "pkg.module:factory"
A factory takes no arguments and returns one Wrapper / Capability.
Two registrants of the same id are a loud collision, never a silent overwrite.
"""
from __future__ import annotations

from importlib.metadata import entry_points

from .contracts import Capability, Wrapper

WRAPPER_GROUP = "agents_store.wrappers"
CAPABILITY_GROUP = "agents_store.capabilities"


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self) -> None:
        self.wrappers: dict[str, Wrapper] = {}
        self.capabilities: dict[str, Capability] = {}

    def register_wrapper(self, w: Wrapper) -> Wrapper:
        if not isinstance(w, Wrapper):
            raise RegistryError(f"{w!r} does not satisfy the Wrapper protocol")
        if w.id in self.wrappers:
            raise RegistryError(f"wrapper id collision: {w.id!r} already registered")
        self.wrappers[w.id] = w
        return w

    def register_capability(self, c: Capability) -> Capability:
        if not isinstance(c, Capability):
            raise RegistryError(f"{c!r} does not satisfy the Capability protocol")
        if c.id in self.capabilities:
            raise RegistryError(f"capability id collision: {c.id!r} already registered")
        if c.mode not in ("render", "lens"):
            raise RegistryError(f"capability {c.id!r}: mode must be render|lens, got {c.mode!r}")
        self.capabilities[c.id] = c
        return c

    def wrapper(self, wid: str) -> Wrapper:
        try:
            return self.wrappers[wid]
        except KeyError:
            raise RegistryError(f"no wrapper registered under {wid!r}") from None

    def load_entry_points(self) -> None:
        for ep in entry_points(group=WRAPPER_GROUP):
            self.register_wrapper(ep.load()())
        for ep in entry_points(group=CAPABILITY_GROUP):
            self.register_capability(ep.load()())
