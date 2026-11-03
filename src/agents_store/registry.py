"""Extension point: wrappers, capabilities, domains and violation ids register here.

Entry-point groups (pyproject of an extension package):
    [project.entry-points."agents_store.wrappers"]       name = "pkg.module:factory"
    [project.entry-points."agents_store.capabilities"]   name = "pkg.module:factory"
    [project.entry-points."agents_store.violation_ids"]  name = "pkg.module:factory"
    [project.entry-points."agents_store.domains"]        name = "pkg.module:factory"
A factory takes no arguments and returns one Wrapper / Capability /
DomainViolationId / DomainProvider. Two registrants of the same id are a loud
collision, never a silent overwrite.

Domain violation ids that match a kernel id from the vendored
kernel-proposal.json are refused. The owning domain registers its own ids;
agents-store does not ship first-party domain ids in that group (same pattern
as the empty wrappers / capabilities entry-point groups). First-party domain
providers (MORe) register via the domains entry-point group in this package.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.metadata import entry_points
from importlib.resources import files

from .contracts import Capability, DomainProvider, DomainViolationId, Wrapper

WRAPPER_GROUP = "agents_store.wrappers"
CAPABILITY_GROUP = "agents_store.capabilities"
VIOLATION_ID_GROUP = "agents_store.violation_ids"
DOMAIN_GROUP = "agents_store.domains"

# Pin: Cypoe/more-framework@504c85f lean-model/kernel-proposal.json (byte-identical vendored copy).
MORE_FRAMEWORK_PIN = "504c85f2854a66da9d4cb165f3559cd13c855ec2"
MORE_FRAMEWORK_REPLAY_REPO = "Cypoe/more-framework"
KERNEL_PROPOSAL_SHA256 = (
    "3ffd00015b398ede4d5f7da852a98732cb48d3490a09eee66b5a4201e30070ec"
)
REPLAY_MCDC_SHA256 = "a9adf15b9e1ecf93d38d3005d96872bae4c4f570fa1191c47395cdb2cf07e6b5"

_KERNEL_ID_LIST_KEYS = (
    "violations",
    "violations_added_v4",
    "refusals",
    "must_not_reuse_for_board_gates",
)
_SEVERITIES = frozenset({"refusal", "warning"})


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
def _kernel_spec() -> dict:
    raw = files("agents_store.more").joinpath("kernel-proposal.json").read_text(
        encoding="utf-8"
    )
    return json.loads(raw)


@lru_cache(maxsize=1)
def kernel_proposal_sha256() -> str:
    """SHA-256 of the vendored kernel-proposal.json bytes."""
    data = files("agents_store.more").joinpath("kernel-proposal.json").read_bytes()
    return hashlib.sha256(data).hexdigest()


def replay_contract_root():
    """Directory containing vendored replay/fixtures from more-framework."""
    return files("agents_store.more").joinpath("replay_contract")


def verify_replay_contract_manifest() -> list[str]:
    """Return errors if MANIFEST.sha256 does not match replay_contract files."""
    root = replay_contract_root()
    manifest = root.joinpath("MANIFEST.sha256")
    if not manifest.is_file():
        return ["replay_contract/MANIFEST.sha256 missing"]
    errs: list[str] = []
    lines = manifest.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        if not rel:
            errs.append(f"bad manifest line: {line!r}")
            continue
        path = root.joinpath(rel)
        if not path.is_file():
            errs.append(f"replay_contract/{rel} missing")
            continue
        if rel == "MANIFEST.sha256":
            body = "\n".join(ln for ln in lines if not ln.endswith("  MANIFEST.sha256"))
            if body:
                body += "\n"
            got = hashlib.sha256(body.encode("utf-8")).hexdigest()
        else:
            got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != digest:
            errs.append(f"replay_contract/{rel}: sha256 mismatch")
    mcdc = root.joinpath("mcdc.json")
    if mcdc.is_file():
        got = hashlib.sha256(mcdc.read_bytes()).hexdigest()
        if got != REPLAY_MCDC_SHA256:
            errs.append(
                f"replay_contract/mcdc.json: expected sha256 {REPLAY_MCDC_SHA256}, got {got}"
            )
    return errs


@lru_cache(maxsize=1)
def kernel_artifact_types() -> frozenset[str]:
    """Artifact type ids from kernel-proposal.json layers.artifact_types."""
    return frozenset(_kernel_spec()["layers"]["artifact_types"])


@lru_cache(maxsize=1)
def kernel_relation_types() -> frozenset[str]:
    """Relation type keys from kernel-proposal.json layers.relations.types."""
    return frozenset(_kernel_spec()["layers"]["relations"]["types"])


@lru_cache(maxsize=1)
def kernel_relation_reverse_names() -> frozenset[str]:
    """Reverse relation names declared on kernel relation types (e.g. mapped_from)."""
    types = _kernel_spec()["layers"]["relations"]["types"]
    out: set[str] = set()
    for spec in types.values():
        if isinstance(spec, dict):
            rev = spec.get("reverse")
            if isinstance(rev, str):
                out.add(rev)
    return frozenset(out)


@lru_cache(maxsize=1)
def kernel_violation_ids() -> frozenset[str]:
    """Ids named by the vendored MORe kernel-proposal.json.

    Domains must not register these; they belong to the product-management
    domain (more-framework), not to a domain package.
    """
    found: set[str] = set()
    _collect_kernel_ids(_kernel_spec(), found)
    return frozenset(found)


class Registry:
    def __init__(self) -> None:
        self.wrappers: dict[str, Wrapper] = {}
        self.capabilities: dict[str, Capability] = {}
        self.violation_ids: dict[str, DomainViolationId] = {}
        self.domains: dict[str, DomainProvider] = {}

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
        if not v.provenance_ref or not isinstance(v.provenance_ref, str):
            raise RegistryError(
                f"violation id {v.id!r}: provenance_ref is required"
            )
        if v.severity not in _SEVERITIES:
            raise RegistryError(
                f"violation id {v.id!r}: severity must be refusal|warning, "
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

    def register_domain(self, d: DomainProvider) -> DomainProvider:
        if not isinstance(d, DomainProvider):
            raise RegistryError(f"{d!r} does not satisfy the DomainProvider protocol")
        if not d.name or not isinstance(d.name, str):
            raise RegistryError("domain name must be a non-empty string")
        if d.name in self.domains:
            raise RegistryError(f"domain name collision: {d.name!r} already registered")
        self.domains[d.name] = d
        return d

    def domain(self, name: str) -> DomainProvider:
        try:
            return self.domains[name]
        except KeyError:
            raise RegistryError(f"no domain registered under {name!r}") from None

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
        for ep in entry_points(group=DOMAIN_GROUP):
            self.register_domain(ep.load()())
