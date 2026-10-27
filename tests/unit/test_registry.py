"""Registry contract tests."""
import unittest
from dataclasses import dataclass

from agents_store import (
    AttrSpec,
    DomainViolationId,
    PutResult,
    Registry,
    RegistryError,
    kernel_violation_ids,
)
from agents_store.registry import VIOLATION_ID_GROUP


@dataclass
class ToyWrapper:
    id: str = "toy"
    namespace: str = "toy"

    def attrs(self):
        return [AttrSpec("toy:thing", "text")]

    def get(self, e, view):
        return str(view.get("toy:thing", ""))

    def put(self, representation, e, view):
        return PutResult()


@dataclass
class ToyCapability:
    id: str = "toy-cap"
    in_kind: str = "text"
    out_kind: str = "text"
    mode: str = "render"

    def run(self, value, ctx):
        return value


def _toy_violation(**kw):
    base = dict(
        id="example_domain_check",
        domain="example.domain",
        severity="refusal",
        source="docs/example.md#checks",
        when="An example condition fails.",
    )
    base.update(kw)
    return DomainViolationId(**base)


class TestRegistry(unittest.TestCase):
    def test_register_and_lookup(self):
        reg = Registry()
        w = ToyWrapper()
        reg.register_wrapper(w)
        self.assertIs(reg.wrapper("toy"), w)

    def test_duplicate_wrapper_id_refused(self):
        reg = Registry()
        reg.register_wrapper(ToyWrapper())
        with self.assertRaises(RegistryError):
            reg.register_wrapper(ToyWrapper())

    def test_non_wrapper_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.register_wrapper(object())

    def test_capability_register(self):
        reg = Registry()
        c = ToyCapability()
        reg.register_capability(c)
        self.assertIs(reg.capabilities["toy-cap"], c)

    def test_capability_bad_mode_refused(self):
        reg = Registry()
        c = ToyCapability(mode="write")
        with self.assertRaises(RegistryError):
            reg.register_capability(c)

    def test_unknown_wrapper_lookup_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.wrapper("missing")


class TestDomainViolationIds(unittest.TestCase):
    def test_register_and_lookup(self):
        reg = Registry()
        v = _toy_violation()
        reg.register_violation_id(v)
        self.assertIs(reg.violation_id("example_domain_check"), v)
        self.assertIs(reg.violation_ids["example_domain_check"], v)

    def test_diagnostic_severity_accepted(self):
        reg = Registry()
        v = _toy_violation(id="example_loud_warn", severity="diagnostic")
        reg.register_violation_id(v)
        self.assertEqual(reg.violation_id("example_loud_warn").severity, "diagnostic")

    def test_duplicate_id_refused(self):
        reg = Registry()
        reg.register_violation_id(_toy_violation())
        with self.assertRaises(RegistryError) as cm:
            reg.register_violation_id(_toy_violation(domain="other.domain"))
        self.assertIn("collision", str(cm.exception))

    def test_kernel_id_refused(self):
        reg = Registry()
        kernel = kernel_violation_ids()
        self.assertIn("status_hand_set", kernel)
        with self.assertRaises(RegistryError) as cm:
            reg.register_violation_id(
                _toy_violation(id="status_hand_set", domain="example.domain")
            )
        self.assertIn("kernel", str(cm.exception))

    def test_bad_severity_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.register_violation_id(_toy_violation(severity="warning"))

    def test_missing_domain_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.register_violation_id(_toy_violation(domain=""))

    def test_missing_source_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.register_violation_id(_toy_violation(source=""))

    def test_non_dataclass_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.register_violation_id(object())

    def test_unknown_lookup_refused(self):
        reg = Registry()
        with self.assertRaises(RegistryError):
            reg.violation_id("missing")

    def test_entry_point_group_name(self):
        self.assertEqual(VIOLATION_ID_GROUP, "agents_store.violation_ids")

    def test_kernel_ids_include_drift_and_board(self):
        ids = kernel_violation_ids()
        self.assertIn("derivative_stale", ids)
        self.assertIn("generated_provenance_missing", ids)
        self.assertIn("board_evidence_source_invalid", ids)
        self.assertIn("envelope_invalid", ids)
        # Domain example ids must not be in the kernel set.
        self.assertNotIn("prose_string_missing", ids)
        self.assertNotIn("prose_language_fallback", ids)


if __name__ == "__main__":
    unittest.main()
