"""agents-store: one identity, many lawful projections."""
from .contracts import (
    AttrSpec, Capability, CapabilityPath, Change, Datom, GapFill,
    DomainViolationId, KindSpec, PutResult, Refusal, Wrapper,
)
from .db import connect
from .registry import Registry, RegistryError, kernel_violation_ids

__version__ = "0.0.1"

__all__ = [
    "AttrSpec", "Capability", "CapabilityPath", "Change", "Datom", "GapFill",
    "DomainViolationId", "KindSpec", "PutResult", "Refusal", "Wrapper",
    "connect", "Registry", "RegistryError", "kernel_violation_ids",
    "__version__",
]
