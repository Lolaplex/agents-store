"""Gates digest witnesses into verification events (kernel
derived_status.gates: "gates digest witnesses into verification events").

A witness is code that actually ran: run_witness() executes a command and
records its exit code and output digests. A Gate turns a witness into a
verification event pinned to subject@version (test stage) or to a
release baseline (production stage). It never writes a status.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .events import Event, now


@dataclass(frozen=True)
class Witness:
    command: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    started_at: str
    finished_at: str


def run_witness(command: Sequence[str], cwd: str | Path | None = None,
                timeout: float = 600) -> Witness:
    started = now()
    proc = subprocess.run(list(command), cwd=cwd, capture_output=True, timeout=timeout)
    return Witness(
        command=tuple(command),
        cwd=str(Path(cwd or ".").resolve()),
        exit_code=proc.returncode,
        stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(proc.stderr).hexdigest(),
        started_at=started,
        finished_at=now(),
    )


@dataclass(frozen=True)
class Gate:
    id: str
    method: str
    actor: str

    def digest(self, witness: Witness, *, subject: str, pinned_against: str,
               stage: str = "test", check: str | None = None) -> Event:
        """Exit code 0 is pass, anything else is fail. The witness travels
        in the event body so the verification names what actually ran."""
        body = {
            "gate": self.id,
            "method": self.method,
            "result": "pass" if witness.exit_code == 0 else "fail",
            "stage": stage,
            "witness": asdict(witness),
        }
        if check:
            body["check"] = check
        return Event("verification", self.actor, (subject,), (pinned_against,),
                     at=witness.finished_at, body=body,
                     provenance=f"gate:{self.id}")
