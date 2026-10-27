"""Extension point: wrappers, capabilities and domain violation ids register here.

Entry-point groups (pyproject of an extension package):
    [project.entry-points."agents_store.wrappers"]       name = "pkg.module:factory"
    [project.entry-points."agents_store.capabilities"]   name = "pkg.module:factory"
    [project.entry-points."agents_store.violation_ids"]  name = "pkg.module:factory"
A factory takes no arguments and returns one Wrapper / Capability /
DomainViolationId. Two registrants of the same id are a loud collision, never
a silent overwrite.

Domain violation ids that match a kernel id from the vendored
kernel-proposal.json are refused. The owning domain registers its own ids;
agents-store does not ship first-party domain ids in this group (same pattern
as the empty wrappers / capabilities entry-point groups).
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.metadata import entry_points
from importlib.resources import files

from .contracts import Capability, DomainViolationId, Wrapper

WRAPPER_GROUP = "agents_store.wrappers"
CAPABILITY_GROUP = "agents_store.capabilities"
VIOLATION_ID_GROUP = "agents_store.violation_ids"

_KERNEL_ID_LIST_KEYS = (
    "violations",
    "violations_added_v4",
    "refusals",
    "must_not_reuse_for_board_gates",
)
_SEVERITIES = frozenset({"refusal", "diagnostic"})


class RegistryError(ValueError):
    pass


def _collect_kernel_ids(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _KERNEL_ID_LIST_KEYS and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        out.add(item)
                    elif isinstance(item, dict):
                        vid = item.get("id")
                        if isinstance(vid, str):
                            out.add(vid)
            else:
                _collect_kernel_ids(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_kernel_ids(item, out)


@lru_cache(maxsize=1)
def kernel_violation_ids() -> frozenset[str]:
    """Ids named by the vendored MORe kernel-proposal.json.

    Domains must not register these; they belong to the product-management
    domain (more-framework), not to a domain package.
    """
    raw = files("agents_store.more").joinpath("kernel-proposal.json").read_text(
        encoding="utf-8"
    )
    found: set[str] = set()
    _collect_kernel_ids(json.loads(raw), found)
    return frozenset(found)


class Registry:
    def __init__(self) -> None:
        self.wrappers: dict[str, Wrapper] = {}
        self.capabilities: dict[str, Capability] = {}
        self.violation_ids: dict[str, DomainViolationId] = {}

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

    def register_violation_id(self, v: DomainViolationId) -> DomainViolationId:
        if not isinstance(v, DomainViolationId):
            raise RegistryError(f"{v!r} is not a DomainViolationId")
        if not v.id or not isinstance(v.id, str):
            raise RegistryError("violation id must be a non-empty string")
        if not v.domain or not isinstance(v.domain, str):
            raise RegistryError(f"violation id {v.id!r}: domain is required")
        if not v.source or not isinstance(v.source, str):
            raise RegistryError(f"violation id {v.id!r}: source (provenance) is required")
        if v.severity not in _SEVERITIES:
            raise RegistryError(
                f"violation id {v.id!r}: severity must be refusal|diagnostic, "
                f"got {v.severity!r}"
            )
        if v.id in kernel_violation_ids():
            raise RegistryError(
                f"violation id {v.id!r} collides with a MORe kernel id; "
                f"register domain ids only"
            )
        if v.id in self.violation_ids:
            raise RegistryError(
                f"violation id collision: {v.id!r} already registered "
                f"(domain {self.violation_ids[v.id].domain!r})"
            )
        self.violation_ids[v.id] = v
        return v

    def wrapper(self, wid: str) -> Wrapper:
        try:
            return self.wrappers[wid]
        except KeyError:
            raise RegistryError(f"no wrapper registered under {wid!r}") from None

    def violation_id(self, vid: str) -> DomainViolationId:
        try:
            return self.violation_ids[vid]
        except KeyError:
            raise RegistryError(f"no violation id registered under {vid!r}") from None

    def load_entry_points(self) -> None:
        for ep in entry_points(group=WRAPPER_GROUP):
            self.register_wrapper(ep.load()())
        for ep in entry_points(group=CAPABILITY_GROUP):
            self.register_capability(ep.load()())
        for ep in entry_points(group=VIOLATION_ID_GROUP):
            self.register_violation_id(ep.load()())
