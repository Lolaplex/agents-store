"""Shared types every module and extension agrees on.

Changing anything here is a contract change (see docs/tasks/README.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

ValueType = Literal["text", "instant", "int", "bool", "ref", "json"]
Cardinality = Literal["one", "many"]
TxOp = Literal["assert", "evolve", "split", "merge", "correct", "retire"]
CapabilityMode = Literal["render", "lens"]
ViolationSeverity = Literal["refusal", "warning"]

# An entity as a wrapper sees it: attr name -> value (cardinality 'many' -> tuple of values).
EntityView = Mapping[str, Any]


@dataclass(frozen=True)
class AttrSpec:
    name: str
    value_type: ValueType
    cardinality: Cardinality = "one"
    doc: str = ""


@dataclass(frozen=True)
class GapFill:
    """Declared gap-filling rule. Derived values are shown as derived, never written back."""
    attr: str
    from_attrs: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class KindSpec:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    derivations: tuple[GapFill, ...] = ()


@dataclass(frozen=True)
class Datom:
    e: str
    a: str
    v: Any
    tx: int
    added: bool


@dataclass(frozen=True)
class Change:
    """One proposed assertion or retraction. e=None means 'the entity this put creates'."""
    e: str | None
    a: str
    v: Any
    added: bool = True


@dataclass(frozen=True)
class Refusal:
    wrapper: str
    reason: str
    e: str | None = None
    a: str | None = None
    payload: str | None = None


@dataclass(frozen=True)
class PutResult:
    changes: tuple[Change, ...] = ()
    refusals: tuple[Refusal, ...] = ()


@runtime_checkable
class Wrapper(Protocol):
    """A pure lens between an entity view and one representation (text).

    No I/O: folders, servers and files live in adapters that call get/put.
    Lens laws (checked by certify): GetPut  put(get(v), v) has no changes;
    PutGet  get(apply(v, put(r, v))) == r over the attrs this wrapper may write.
    """

    id: str
    namespace: str

    def attrs(self) -> Sequence[AttrSpec]: ...

    def get(self, e: str, view: EntityView) -> str: ...

    def put(self, representation: str, e: str | None, view: EntityView | None) -> PutResult: ...


@runtime_checkable
class Capability(Protocol):
    """A registered interpretation step in_kind -> out_kind (e.g. 'markdown' -> 'html')."""

    id: str
    in_kind: str
    out_kind: str
    mode: CapabilityMode

    def run(self, value: Any, ctx: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class DomainViolationId:
    """A domain-owned violation or warning id, registered in the open registrar.

    Kernel ids from the vendored kernel-proposal.json are reserved: a domain
    must not register one. The owning domain registers its own ids (entry point
    or in-process); agents-store does not hard-code them.

    Fields:
      id: stable snake_case id (the public contract).
      domain: owning domain (for example "agents-design.template-engine").
      severity: "refusal" (blocks) or "warning" (loud, recorded, does not block).
      provenance_ref: provenance reference (doc path, pin, URL, or SAID).
      fires_when: English text that says when the id fires (ASD-STE100).
    """
    id: str
    domain: str
    severity: ViolationSeverity
    provenance_ref: str
    fires_when: str = ""


@dataclass(frozen=True)
class CapabilityPath:
    steps: tuple[str, ...] = field(default_factory=tuple)  # capability ids, in order
