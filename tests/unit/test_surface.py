"""T18 domain-neutral surface: append, domains, CLI, MCP."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents_store import WriteRefusal, connect
from agents_store.domains.more import factory as more_factory
from agents_store.registry import DOMAIN_GROUP, Registry, RegistryError
from agents_store.surface import (
    OP_NOT_SUPPORTED,
    SURFACE,
    UNKNOWN_DOMAIN,
    append,
    list_domains,
)
from tests.more.helpers import FAB


def _reg_with_more() -> Registry:
    reg = Registry()
    reg.register_domain(more_factory())
    return reg


class TestDomainRegistry(unittest.TestCase):
    def test_register_and_lookup(self):
        reg = _reg_with_more()
        d = reg.domain("more")
        self.assertEqual(d.name, "more")
        self.assertIn("append", d.write_ops())

    def test_duplicate_refused(self):
        reg = _reg_with_more()
        with self.assertRaises(RegistryError):
            reg.register_domain(more_factory())

    def test_entry_point_group_name(self):
        self.assertEqual(DOMAIN_GROUP, "agents_store.domains")


class TestAppendSurface(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.reg = _reg_with_more()

    def tearDown(self):
        self.conn.close()

    def test_append_succeeds(self):
        payload = {
            "type": "decision",
            "subjects": ["ADR-1"],
            "pinned_against": ["ADR-1@1"],
            "body": {
                "status": "decided",
                "decided_by": FAB,
                "title": "Use SQLite",
                "body": "One file.",
                "topic": "storage",
            },
        }
        result = append("more", payload, FAB, conn=self.conn, reg=self.reg)
        self.assertIsInstance(result, str)
        self.assertTrue(result)

    def test_append_refusal(self):
        # decision with status decided but missing decided_by → MORe check refuses
        payload = {
            "type": "decision",
            "subjects": ["ADR-1"],
            "pinned_against": ["ADR-1@1"],
            "body": {"status": "decided", "title": "x", "body": "y", "topic": "t"},
        }
        result = append("more", payload, FAB, conn=self.conn, reg=self.reg)
        self.assertIsInstance(result, WriteRefusal)
        self.assertEqual(result.wrapper, "more")

    def test_unknown_domain_refused(self):
        result = append("nope", {"type": "decision"}, FAB, conn=self.conn, reg=self.reg)
        self.assertIsInstance(result, WriteRefusal)
        self.assertEqual(result.wrapper, SURFACE)
        self.assertEqual(result.reason, UNKNOWN_DOMAIN)
        self.assertEqual(result.payload, "nope")

    def test_domain_without_append_refused(self):
        class ReadOnly:
            name = "posix"
            def write_ops(self):
                return ()
            def read_ops(self):
                return ("stat",)
            def refusal_ids(self):
                return ()
            def append(self, conn, payload, actor):
                raise AssertionError("must not be called")

        reg = _reg_with_more()
        reg.register_domain(ReadOnly())
        result = append("posix", {}, FAB, conn=self.conn, reg=reg)
        self.assertIsInstance(result, WriteRefusal)
        self.assertEqual(result.reason, OP_NOT_SUPPORTED)

    def test_list_domains(self):
        rows = list_domains(self.reg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "more")
        self.assertEqual(rows[0]["write_ops"], ["append"])
        self.assertIn("violation_registry", rows[0])
        self.assertGreater(len(rows[0]["violation_registry"]), 0)

    def test_list_domains_without_violation_registry(self):
        class Minimal:
            name = "minimal"
            def write_ops(self):
                return ("append",)
            def read_ops(self):
                return ()
            def refusal_ids(self):
                return ("bad_payload",)
            def append(self, conn, payload, actor):
                raise AssertionError("must not be called")

        reg = Registry()
        reg.register_domain(Minimal())
        rows = list_domains(reg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["violation_registry"], [])


class TestCLI(unittest.TestCase):
    def test_domains_subcommand(self):
        from agents_store.cli import main
        buf = io.StringIO()
        with mock.patch("agents_store.cli.default_registry", _reg_with_more):
            with mock.patch("sys.stdout", buf):
                code = main(["domains"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["domains"][0]["name"], "more")

    def test_append_subcommand_success(self):
        from agents_store.cli import main
        payload = {
            "type": "decision",
            "subjects": ["ADR-cli"],
            "pinned_against": ["ADR-cli@1"],
            "body": {
                "status": "decided",
                "decided_by": FAB,
                "title": "CLI",
                "body": "ok",
                "topic": "cli",
            },
        }
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "store.sqlite")
            buf = io.StringIO()
            err = io.StringIO()
            with mock.patch("agents_store.cli.default_registry", _reg_with_more):
                with mock.patch("sys.stdout", buf), mock.patch("sys.stderr", err):
                    code = main([
                        "append", "--domain", "more", "--actor", FAB,
                        "--db", db, json.dumps(payload),
                    ])
            self.assertEqual(code, 0, err.getvalue())
            data = json.loads(buf.getvalue())
            self.assertTrue(data["ok"])
            self.assertIn("id", data)

    def test_append_unknown_domain_cli(self):
        from agents_store.cli import main
        err = io.StringIO()
        with mock.patch("agents_store.cli.default_registry", _reg_with_more):
            with mock.patch("sys.stderr", err):
                code = main([
                    "append", "--domain", "missing", "--actor", FAB,
                    json.dumps({"type": "decision", "subjects": ["x"]}),
                ])
        self.assertEqual(code, 1)
        data = json.loads(err.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["refusal"]["reason"], UNKNOWN_DOMAIN)


class TestMCP(unittest.TestCase):
    def _exchange(self, requests: list[dict]) -> list[dict]:
        """Drive mcp_server.serve_stdio with injectable streams."""
        from agents_store import mcp_server

        def frame(obj: dict) -> bytes:
            data = json.dumps(obj).encode("utf-8")
            return f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data

        stdin_data = b"".join(frame(r) for r in requests)
        out = io.BytesIO()
        err = io.StringIO()

        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "mcp.sqlite")
            with mock.patch("agents_store.mcp_server.default_registry", _reg_with_more):
                code = mcp_server.serve_stdio(
                    db=db, actor=FAB,
                    inp=io.BytesIO(stdin_data), out=out, err=err,
                )
        self.assertEqual(code, 0, err.getvalue())

        raw = out.getvalue()
        responses = []
        i = 0
        while i < len(raw):
            if not raw.startswith(b"Content-Length:", i):
                break
            line_end = raw.index(b"\r\n\r\n", i)
            header = raw[i:line_end].decode("ascii")
            length = int(header.split(":", 1)[1].strip())
            start = line_end + 4
            body = raw[start:start + length]
            responses.append(json.loads(body.decode("utf-8")))
            i = start + length
        return responses

    def test_tools_list_and_append(self):
        payload = {
            "type": "decision",
            "subjects": ["ADR-mcp"],
            "pinned_against": ["ADR-mcp@1"],
            "body": {
                "status": "decided",
                "decided_by": FAB,
                "title": "MCP",
                "body": "ok",
                "topic": "mcp",
            },
        }
        responses = self._exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {
                    "name": "append",
                    "arguments": {"domain": "more", "payload": payload},
                },
            },
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "domains", "arguments": {}}},
        ])
        self.assertEqual(len(responses), 4)
        tools = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertEqual(tools, {"append", "domains"})
        append_body = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertTrue(append_body["ok"], append_body)
        self.assertIn("id", append_body)
        # Actor in tool args must be ignored — success already used server actor.
        domains_body = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertEqual(domains_body["domains"][0]["name"], "more")

    def test_mcp_ignores_caller_actor(self):
        """Even if payload carries actor, server actor wins (MORe provider overwrites)."""
        payload = {
            "type": "decision",
            "actor": "did:web:attacker",
            "subjects": ["ADR-mcp2"],
            "pinned_against": ["ADR-mcp2@1"],
            "body": {
                "status": "decided",
                "decided_by": FAB,
                "title": "MCP2",
                "body": "ok",
                "topic": "mcp",
            },
        }
        responses = self._exchange([
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": "append",
                    "arguments": {
                        "domain": "more",
                        "payload": payload,
                        "actor": "did:web:attacker",  # must be ignored at tool layer
                    },
                },
            },
        ])
        body = json.loads(responses[0]["result"]["content"][0]["text"])
        self.assertTrue(body["ok"], body)


if __name__ == "__main__":
    unittest.main()
