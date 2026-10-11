"""Registry contract tests."""
import unittest
from dataclasses import dataclass

from agents_store import AttrSpec, PutResult, Registry, RegistryError


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


if __name__ == "__main__":
    unittest.main()
