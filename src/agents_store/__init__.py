"""agents-store: one identity, many lawful projections."""
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

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

try:
    __version__ = _version("agents-store")
except _PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0+source"

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
