"""agents-store: one identity, many lawful projections."""
from .contracts import (
    AttrSpec, Capability, CapabilityPath, Change, Datom, DomainProvider, GapFill,
    DomainViolationId, KindSpec, PutResult, WriteRefusal, Wrapper,
)
from .db import connect
from .registry import (
    Registry,
    RegistryError,
    KERNEL_PROPOSAL_SHA256,
    MORE_FRAMEWORK_PIN,
    kernel_artifact_types,
    kernel_proposal_sha256,
    kernel_relation_reverse_names,
    kernel_relation_types,
    kernel_violation_ids,
)

__version__ = "0.0.1"

__all__ = [
    "AttrSpec", "Capability", "CapabilityPath", "Change", "Datom", "DomainProvider", "GapFill",
    "DomainViolationId", "KindSpec", "PutResult", "WriteRefusal", "Wrapper",
    "connect", "Registry", "RegistryError",
    "KERNEL_PROPOSAL_SHA256", "MORE_FRAMEWORK_PIN",
    "kernel_artifact_types", "kernel_proposal_sha256",
    "kernel_relation_reverse_names", "kernel_relation_types",
    "kernel_violation_ids",
    "__version__",
]
