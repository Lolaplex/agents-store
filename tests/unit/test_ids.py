"""ids.mint: unique, 26-char Crockford, sortable by creation order."""
import unittest

from agents_store import ids


class TestMint(unittest.TestCase):
    def test_unique_10k(self):
        seen = {ids.mint() for _ in range(10_000)}
        self.assertEqual(len(seen), 10_000)

    def test_sortable_by_creation_order(self):
        generated = [ids.mint() for _ in range(10_000)]
        self.assertEqual(generated, sorted(generated))

    def test_shape(self):
        eid = ids.mint()
        self.assertEqual(len(eid), 26)
        self.assertTrue(all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in eid))


if __name__ == "__main__":
    unittest.main()
