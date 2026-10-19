"""Profile: the declared, data-only part of the kernel.

Levels, per-level questions and the JWF status model are read from the
spec file (lean-model/kernel-proposal.json), never restated in code.
Implementation knobs the spec leaves open live in profiles/default.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

SPEC_PATH = Path(__file__).resolve().parent / "kernel-proposal.json"
SETTINGS_PATH = Path(__file__).resolve().parent / "profiles" / "default.json"


@dataclass(frozen=True)
class Question:
    level: str
    en: str
    de: str | None
    src: str


@dataclass(frozen=True)
class Phase:
    name: str
    states: tuple[str, ...]


@dataclass(frozen=True)
class StatusModel:
    """A declared state machine. Every state is derived; nothing writes one."""
    name: str
    phases: tuple[Phase, ...]
    gates: Mapping[str, Any]
    # jira_status_model.acceptance: topic, default acceptor roles, reached state
    acceptance: Mapping[str, Any]

    @property
    def states(self) -> tuple[str, ...]:
        return tuple(s for p in self.phases for s in p.states)


@dataclass(frozen=True)
class Profile:
    spec_version: Any
    levels: tuple[str, ...]
    parent: Mapping[str, str | None]
    questions: Mapping[str, Question]
    status_model: StatusModel
    settings: Mapping[str, Any]

    def setting(self, key: str) -> Any:
        return self.settings[key]

    def with_settings(self, **kw: Any) -> "Profile":
        """A copy with some settings changed (e.g. roles, acceptor_roles)."""
        return replace(self, settings={**self.settings, **kw})

    def roles(self, principal: str | None) -> tuple[str, ...]:
        """Board roles a principal holds (Lean Profile.roles)."""
        return tuple(self.settings.get("roles", {}).get(principal or "", ()))


def _parents(levels: tuple[str, ...], raw: Mapping[str, str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {lvl: None for lvl in levels}
    for children, parent in raw.items():
        for child in children.split("|"):
            out[child] = parent
    return out


def load_profile(spec_path: Path | str = SPEC_PATH,
                 settings_path: Path | str = SETTINGS_PATH) -> Profile:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    h = spec["hierarchy"]
    levels = tuple(h["levels"])
    questions = {
        lvl: Question(lvl, q.get("en") or "", q.get("de"), q.get("src") or "")
        for lvl, q in h.get("questions", {}).items()
    }
    jwf = spec["jira_status_model"]
    model = StatusModel(
        name="jira_status_model",
        phases=tuple(Phase(p["phase"], tuple(p["states"])) for p in jwf["phases"]),
        gates={k: v for k, v in jwf["gates"].items() if k.startswith("QG")},
        acceptance=jwf["acceptance"],
    )
    return Profile(
        spec_version=spec.get("version"),
        levels=levels,
        parent=_parents(levels, h["parent"]),
        questions=questions,
        status_model=model,
        settings={k: v for k, v in settings.items() if not k.startswith("_")},
    )
