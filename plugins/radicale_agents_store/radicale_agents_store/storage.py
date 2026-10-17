"""Radicale storage backend over the agents-store canonical layer.

Model: two fixed collections, `calendar` (entities carrying `when`) and
`tasks` (entities carrying `status`). There is no collection table —
membership is a view over canonical attrs; arbitrary collections are
refused. Item identity: `ical:href` is the projection path datum
(never the entity id); UID in emitted items is always the entity id.

Refusal law: every wrapper/store refusal lands in `refusal` AND surfaces
as an HTTP error (ValueError -> Radicale BAD_REQUEST / conflict).
"""
from __future__ import annotations

import contextlib
import os
import posixpath
import threading
import time
from email.utils import formatdate
from types import SimpleNamespace
from typing import Iterable, Iterator, Mapping, Optional

from radicale import pathutils
from radicale.item import Item
from radicale.storage import BaseCollection, BaseStorage

import agents_store
from agents_store.certify import certify, grant_roundtrip, register_wrapper
from agents_store.contracts import Change
from agents_store.grant import is_writable
from agents_store.store import Store
from agents_store.wrappers.ical import ICalWrapper

# collection -> attr that grants membership (kinds are structural)
COLLECTIONS = {"calendar": "when", "tasks": "status"}
_MAPPED_ATTRS = ("title", "status", "when", "end")

# Deterministic witness corpus for the ical lens: covers VEVENT, VTODO,
# status round-trip and the lossless ical:extra path. Adapter-owned attrs
# (ical:href, ical:client-uid) are intentionally absent -> PutGet skips
# them, grant_roundtrip still grants them.
_CORPUS = [
    {"title": "a", "when": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"},
    {"title": "b", "status": "open", "when": "2026-01-02T00:00:00Z"},
    {"status": "done"},
    {"title": "c", "when": "2026-01-03T00:00:00Z",
     "ical:extra": ["X-POC-FLAG:1"]},
]


def _db_path(configuration) -> str:
    """Plugin db path: env AGENTS_STORE_DB wins, then
    <storage.filesystem_folder>/agents-store.sqlite, else cwd."""
    env = os.environ.get("AGENTS_STORE_DB")
    if env:
        return env
    try:
        folder = configuration.get("storage", "filesystem_folder")
    except Exception:
        folder = None
    return os.path.join(folder, "agents-store.sqlite") if folder else "agents-store.sqlite"


class Storage(BaseStorage):
    """Radicale storage entry point. Set in config:

        [storage]
        type = radicale_agents_store
    """

    def __init__(self, configuration) -> None:
        super().__init__(configuration)
        self.db_path = _db_path(configuration)
        self.wrapper = ICalWrapper()
        # sqlite objects are thread-affine; Radicale may serve on worker
        # threads -> one connection per thread (WAL allows this).
        self._local = threading.local()
        register_wrapper(self.conn, self.wrapper)
        if not is_writable(self.conn, self.wrapper.id, "when"):
            cert = certify(self.conn, self.wrapper, _CORPUS)
            grant_roundtrip(self.conn, self.wrapper, cert)
        self.conn.commit()
        self._rlock = threading.RLock()
        self._lock = SimpleNamespace(locked=None)
        self._meta: dict[str, dict[str, str]] = {
            "calendar": {"D:displayname": "agents-store calendar",
                         "tag": "VCALENDAR"},
            "tasks": {"D:displayname": "agents-store tasks",
                      "tag": "VCALENDAR"},
        }

    # ---- per-thread store access ----------------------------------------

    @property
    def conn(self):
        if getattr(self._local, "conn", None) is None:
            self._local.conn = agents_store.connect(self.db_path)
            self._local.store = Store(self._local.conn)
        return self._local.conn

    @property
    def store(self) -> Store:
        self.conn  # ensure this thread's pair exists
        return self._local.store

    # ---- BaseStorage ---------------------------------------------------

    def discover(self, path: str, depth: str = "0",
                 child_context_manager=None,
                 user_groups=frozenset()) -> Iterable:
        """Topology: / -> <principal>/ -> {calendar,tasks}/ -> items.

        Collections live under principals because Radicale's rights model
        nests them; principal names are dynamic (any authenticated user),
        so the root enumerates nothing at depth 1."""
        sane = pathutils.strip_path(path)
        parts = [p for p in sane.split("/") if p]
        if not parts:
            yield Collection(self, "")
            return
        head = parts[0]
        if head in COLLECTIONS:
            return  # flat collection paths refused: only under a principal
        if len(parts) == 1:
            yield Collection(self, head)  # principal container
            if depth != "0":
                for name in COLLECTIONS:
                    yield Collection(self, f"{head}/{name}")
            return
        if parts[1] in COLLECTIONS:
            coll = Collection(self, f"{head}/{parts[1]}")
            if len(parts) == 2:
                yield coll
                if depth != "0":
                    yield from coll.get_all()
            else:
                item = coll._item(parts[2])
                if item is not None:
                    yield item

    def move(self, item: Item, to_collection: "Collection",
             to_href: str) -> None:
        e = self._resolve_entity(item.href or "", item.uid)
        if e is None:
            raise ValueError("move: unknown item")
        self.store.transact(
            [Change(e=e, a="ical:href", v=to_href)],
            wrapper="ical", op="assert",
            note=f"caldav MOVE {item.href} -> {to_href}",
        )
        self.conn.commit()

    def create_collection(self, href: str, items=None, props=None):
        name = pathutils.strip_path(href)
        if name.count("/") == 1 and name.rsplit("/", 1)[-1] in COLLECTIONS:
            coll = Collection(self, name)
            if props:
                coll._meta.update(props)
            return coll, {}, []
        # Radicale auto-creates a principal container on first login;
        # single-segment tagless names are tolerated as containers.
        # Tagged or nested collections are refused: membership is a view.
        if "/" not in name and not (props or {}).get("tag") and not items:
            return Collection(self, name), {}, []
        raise ValueError(
            f"collection-refused: only {sorted(COLLECTIONS)} exist; "
            f"membership is a view, not a folder")

    @contextlib.contextmanager
    def acquire_lock(self, mode: str, user: str = "", *args, **kwargs) -> Iterator[None]:
        self._rlock.acquire()
        self._lock.locked = mode
        try:
            yield
        finally:
            self._lock.locked = None
            self._rlock.release()

    def verify(self) -> bool:
        try:
            return self.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except Exception:
            return False

    # ---- entity resolution ---------------------------------------------

    def _resolve_entity(self, href: str, uid: Optional[str] = None) -> Optional[str]:
        """href -> entity. Order: <eid>.ics in the name, stored ical:href
        datum, UID that is itself an entity id."""
        base = href[:-4] if href.endswith(".ics") else href
        if self.store.exists(base):
            return base
        row = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = ?",
            (href,), ).fetchone()
        if row:
            return row[0]
        if uid and self.store.exists(uid):
            return uid
        return None

    def _members(self, attr: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT e FROM v_current WHERE a = ? ORDER BY e", (attr,))]


class Collection(BaseCollection):
    """A membership-view collection: `calendar` or `tasks`."""

    def __init__(self, storage: Storage, path: str) -> None:
        self._storage = storage
        # callers pass the already-sanitized collection name ('', 'calendar',
        # 'tasks'); strip_path would assert on it.
        self._path = path
        self._meta: dict[str, str] = {}

    @property
    def path(self) -> str:
        return self._path

    @property
    def _collection_name(self) -> str:
        """'calendar' | 'tasks' | '' for containers/principals."""
        return self._path.rsplit("/", 1)[-1]

    # ---- items ---------------------------------------------------------

    def _entity_ids(self) -> list[str]:
        attr = COLLECTIONS.get(self._collection_name)
        return self._storage._members(attr) if attr else []

    def _href_of(self, e: str, view: Mapping) -> str:
        return view.get("ical:href") or f"{e}.ics"

    def _item(self, href: str) -> Optional[Item]:
        e = self._storage._resolve_entity(href)
        if e is None:
            return None
        view = self._storage.store.view(e)
        attr = COLLECTIONS.get(self._collection_name)
        if attr and attr not in view:
            return None
        return Item(collection_path=self._path, collection=self,
                    href=self._href_of(e, view),
                    last_modified=formatdate(time.time(), usegmt=True),
                    text=self._storage.wrapper.get(e, view))

    def get_multi(self, hrefs: Iterable[str]):
        for href in hrefs:
            item = self._item(href)
            yield href, item

    def get_all(self):
        for e in self._entity_ids():
            view = self._storage.store.view(e)
            yield Item(collection_path=self._path, collection=self,
                       href=self._href_of(e, view),
                       last_modified=formatdate(time.time(), usegmt=True),
                    text=self._storage.wrapper.get(e, view))

    # ---- writes --------------------------------------------------------

    def upload(self, href: str, item: Item):
        store = self._storage.store
        w = self._storage.wrapper
        old = self._item(href)
        e = self._storage._resolve_entity(href, item.uid)
        view = store.view(e) if e else {}
        res = w.put(item.serialize(), e, view)
        if res.refusals:
            r = res.refusals[0]
            store.record_refusal(r)
            self._storage.conn.commit()
            raise ValueError(f"ical refusal: {r.reason} ({r.payload})")
        changes = list(res.changes)
        if e is None:
            # mint exactly one entity; client UID + href land as data
            changes = [Change(e=None, a=c.a, v=c.v, added=c.added)
                       for c in changes]
            changes.append(Change(e=None, a="ical:href", v=href))
            if item.uid:
                changes.append(Change(e=None, a="ical:client-uid", v=item.uid))
        result = store.transact(changes, wrapper=w.id,
                                note=f"caldav PUT {self._path}/{href}")
        self._storage.conn.commit()
        if result.refusals:
            r = result.refusals[0]
            raise ValueError(f"store refusal: {r.reason} ({r.payload})")
        new_e = e or result.entity
        return self._item_for_entity(new_e), old

    def _item_for_entity(self, e: str) -> Item:
        view = self._storage.store.view(e)
        return Item(collection_path=self._path, collection=self,
                    href=self._href_of(e, view),
                    last_modified=formatdate(time.time(), usegmt=True),
                    text=self._storage.wrapper.get(e, view))

    def delete(self, href: Optional[str] = None) -> None:
        if href is None:
            raise ValueError(
                "collection-refused: fixed membership views cannot be deleted")
        store = self._storage.store
        e = self._storage._resolve_entity(href)
        if e is None:
            raise ValueError(f"not found: {href}")
        view = store.view(e)
        # Retract the round-trip set: the entity loses kind membership and
        # leaves every projection; all datoms stay in history.
        changes = [Change(e=e, a=a, v=view[a], added=False)
                   for a in _MAPPED_ATTRS if a in view]
        for a in sorted(view):
            if a.startswith("ical:"):
                changes.append(Change(e=e, a=a, v=view[a], added=False))
        result = store.transact(
            changes, wrapper="ical", op="retire", note=href,
        )
        self._storage.conn.commit()
        if result.refusals:
            raise ValueError(f"store refusal: {result.refusals[0].reason}")

    # ---- metadata ------------------------------------------------------

    def get_meta(self, key: Optional[str] = None):
        meta = {**self._storage._meta.get(self._collection_name, {}), **self._meta}
        return meta.get(key) if key else meta

    def set_meta(self, props: Mapping[str, str]) -> None:
        # In-memory POC: displayname/desc survive for the process lifetime.
        # Persistence lands with the meta-projection (BACKLOG).
        self._meta.update(props)

    @property
    def last_modified(self) -> str:
        row = self._storage.conn.execute(
            "SELECT MAX(ts) FROM tx").fetchone()
        ts = row[0] if row and row[0] else time.time()
        if isinstance(ts, str):
            try:
                t = time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
                ts = time.mktime(t)
            except ValueError:
                ts = time.time()
        return formatdate(ts, usegmt=True)
