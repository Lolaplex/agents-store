#!/usr/bin/env python3
"""Fetch or verify byte-identical MORe replay fixtures from more-framework.

Source: Cypoe/more-framework @ MORE_FRAMEWORK_PIN (see agents_store.registry).
Writes under src/agents_store/more/replay_contract/ and refreshes MANIFEST.sha256.

Auth: REPO_READ_TOKEN or GITHUB_TOKEN (same pattern as agents-harness private clones).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agents_store.registry import MORE_FRAMEWORK_PIN

REPO = "Cypoe/more-framework"
REPLAY_PREFIX = "replay"

CONTRACT = ROOT / "src" / "agents_store" / "more" / "replay_contract"
MANIFEST = CONTRACT / "MANIFEST.sha256"


def _token() -> str:
    for key in ("REPO_READ_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val.strip()
    sys.stderr.write(
        "sync_more_replay: set REPO_READ_TOKEN or GITHUB_TOKEN for fetch\n"
    )
    sys.exit(1)


def _api(path: str) -> bytes:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={MORE_FRAMEWORK_PIN}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agents-store-sync-more-replay",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _download_file(path: str) -> bytes:
    meta = json.loads(_api(path))
    if meta.get("encoding") == "base64" and "content" in meta:
        raw = meta["content"].replace("\n", "")
        return base64.b64decode(raw)
    download = meta.get("download_url")
    if not download:
        raise RuntimeError(f"no content for {path}")
    req = urllib.request.Request(
        download,
        headers={"Authorization": f"Bearer {_token()}", "User-Agent": "agents-store-sync"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _list_tree(prefix: str) -> list[str]:
    meta = json.loads(_api(prefix))
    if isinstance(meta, dict) and meta.get("type") == "file":
        return [prefix]
    out: list[str] = []
    for entry in meta:
        if entry.get("type") == "file":
            out.append(entry["path"])
        elif entry.get("type") == "dir":
            out.extend(_list_tree(entry["path"]))
    return out


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _manifest_lines() -> list[str]:
    lines: list[str] = []
    for path in sorted(CONTRACT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(CONTRACT).as_posix()
        if rel == "MANIFEST.sha256":
            continue
        lines.append(f"{_sha256_file(path)}  {rel}")
    body = "\n".join(lines) + ("\n" if lines else "")
    digest = _sha256_bytes(body.encode("utf-8"))
    lines.append(f"{digest}  MANIFEST.sha256")
    return lines


def write_manifest() -> None:
    MANIFEST.write_text("\n".join(_manifest_lines()) + "\n", encoding="utf-8")


def verify_manifest() -> list[str]:
    if not MANIFEST.is_file():
        return ["MANIFEST.sha256 missing"]
    errs: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        if not rel:
            errs.append(f"bad manifest line: {line!r}")
            continue
        path = CONTRACT / rel
        if not path.is_file():
            errs.append(f"missing {rel}")
            continue
        if rel == "MANIFEST.sha256":
            body_lines = [
                ln
                for ln in MANIFEST.read_text(encoding="utf-8").splitlines()
                if not ln.endswith("  MANIFEST.sha256")
            ]
            got = _sha256_bytes(("\n".join(body_lines) + "\n").encode("utf-8"))
        else:
            got = _sha256_file(path)
        if got != digest:
            errs.append(f"{rel}: sha256 mismatch (manifest {digest}, file {got})")
    return errs


def fetch() -> None:
    paths = [
        p
        for p in _list_tree(REPLAY_PREFIX)
        if p.endswith(".json") or p.endswith("mcdc.json")
    ]
    for remote in sorted(paths):
        rel = remote.removeprefix(f"{REPLAY_PREFIX}/")
        if remote == f"{REPLAY_PREFIX}/mcdc.json":
            rel = "mcdc.json"
        data = _download_file(remote)
        dest = CONTRACT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    write_manifest()
    print(f"synced {len(paths)} files into {CONTRACT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="Check MANIFEST.sha256 against on-disk replay_contract files",
    )
    args = ap.parse_args()
    if args.verify_only:
        errs = verify_manifest()
        if errs:
            for e in errs:
                print(e, file=sys.stderr)
            sys.exit(1)
        print(f"replay_contract manifest OK ({CONTRACT})")
        return
    try:
        fetch()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"sync_more_replay: HTTP {exc.code} {exc.reason}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
