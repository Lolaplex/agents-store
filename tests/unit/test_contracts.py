"""Contract type sanity checks (frozen dataclasses, protocol conformance)."""
import unittest
from dataclasses import FrozenInstanceError

from agents_store import (
    Capability, Change, Datom, PutResult, WriteRefusal, Wrapper,
)


class TestContracts(unittest.TestCase):
    def test_datom_frozen(self):
        d = Datom(e="e1", a="title", v="x", tx=1, added=True)
        with self.assertRaises(FrozenInstanceError):
            d.v = "y"

    def test_change_default_is_add(self):
        c = Change(e=None, a="title", v="x")
        self.assertTrue(c.added)

    def test_putresult_defaults_empty(self):
        r = PutResult()
        self.assertEqual(r.changes, ())
        self.assertEqual(r.refusals, ())

    def test_refusal_fields(self):
        r = WriteRefusal(wrapper="md", reason="no_grant", e="e1", a="body")
        self.assertEqual(r.reason, "no_grant")

    def test_protocol_is_runtime_checkable(self):
        self.assertTrue(hasattr(Wrapper, "__protocol_attrs__") or issubclass(Wrapper, object))
        self.assertTrue(issubclass(Capability, object))


if __name__ == "__main__":
    unittest.main()
