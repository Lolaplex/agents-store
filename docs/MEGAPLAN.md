---
agent: devin-local
session: gigantic-dive
created: 2026-10-06T22:02:35Z
---
# Megaplan: agents-store, one identity and many lawful projections

Record what this session learned (where the ISAR/plex lineage came from and its missteps, what still holds, the reading list), then define a new repo `agents-store`: a minimal Python+SQLite proof of concept where one entity is a CalDAV event/task (Radicale), a markdown note, and an HTML pane at the same time, with lawful write-back refused by default. Then the phases after it, the parallel ISAR track with its kill date, and the long-range vision.

## 0. Decisions captured (from this session)

| Question | Decision |
|---|---|
| Where the megaplan lives | **New repo `C:\Users\fabi0\repos\agents-store`**, plan at `docs/MEGAPLAN.md`, registered in agents-memory |
| POC substrate | **Python 3.11 + stdlib `sqlite3` first**; a koru store library on a *branch* only after the POC passes |
| POC projections | **CalDAV (Radicale storage plugin) + markdown folder + HTML pane** |
| CalDAV implementation | **Radicale storage plugin**, pinned to a version published ≥7 days ago |
| CalDAV acceptance client | **Thunderbird** (manual) + agents-calendar (scripted, independent witness) |
| License | **core MIT**; Radicale plugin in its own sub-package, **GPLv3** |
| Package shape | **library only** for the POC (no CLI/MCP; demo via `examples/` scripts) |
| ISAR/phi2 line | **continues in parallel** with a kill criterion: native cogen by **2026-11-30**, else freeze |
| "fork koru" | means a **branch** in `W:\src\koru` (a store model as a library), not a hard fork |

## 1. Thesis (one paragraph)

Computation is a convention for interpreting states. "Data" is the state whose interpreter lives elsewhere, i.e. referentially open. Systems fracture because they store *interpretations* (an app's schema, a file path, a DB row, an HTML page) as if they were the thing itself, then reconcile the copies with sync. The fix: one store of **minted identities** with typed attributes, relations and transactions. Every app, file path, protocol and view is a **projection** (wrapper + lens). Projections between two sources are **derived through a shared quotient** (mediators), not hand-written for each pair. A write goes through a projection only when a certificate (witness or proof) grants it: **refused by default**.

## 2. Where we came from: lineage and missteps (lessons become rules)

Lineage (from `isa-physics/docs/session/ARCHAEOLOGY_TOOLCHAIN.md` and `plexus/docs/ARCHEOLOGY.md`):
`isar_plex.py` monolith → `plex/` package (SQLite U-table) → `docs/RFC` reference implementation → `compiler/` AXIR+LLVM (dead) → `plex-agent` fasmg toolchain → `plexus` Rust (retired) → `isar-proofs` host/seed (self-hosting PE emitter, pexec fixpoint) → `phi2` relational corpus + rel.rs.
The oldest thread underneath all of it: Nextcloud apps silo their data; schema→HTML projection; a filesystem privileges one path where "more than one path leads to the same object."

| # | Misstep | Evidence | Rule for agents-store |
|---|---|---|---|
| M1 | ~8 substrates before any result a user could use | lineage above | **No new substrate until POC acceptance passes** |
| M2 | Months spent optimizing the slowest realization while prior art sat unused | session quote: "optimizing the slowest realization… U-table sat as prior art" | Measure against an external baseline before optimizing |
| M3 | Overclaims in docs | ARCHEOLOGY: H₀=67.4 "prediction" (equals Planck 2018 measured value), "Inverse Complexity Law / O(1) contraction", "MicroProofChecker <0.1ms"; "no preferred syntax" while `Kernel` hard-codes decode into `ISKSubtype` | Every claim cites executed evidence; docs pin the tree they measured |
| M4 | Decorative semantics | `isar_snake.html`: game logic in JS, "APP operator: A·R" comments, `kernel_matrices` never read; three inconsistent matrix sets (Lean v1/v2, `bootstrap.sql`) | A label must name code that does the work, or be removed |
| M5 | Lawfulness declared, not proven | `projections.sql`: `is_natural_transformation DEFAULT 1`, `preserves_identity DEFAULT 1` | **Refuse by default**; flags become certificate references |
| M6 | Identity = position | `U(i,s,a,r)` snake rewrites `r`/`s` every tick; plex-agent sequential `tensor_id`; byte stored as float `0.165` and decoded with `int(x*255)` | **Minted IDs, never reused, never positional** |
| M7 | Encoding-level confusion produced false agreement | frag 0017 retracted "rfold → 0 sols" agreement (grammar-1 vs grammar-2); frag 0014 NIL vs encoded-empty-list | The encoding boundary refuses wrong-level input structurally |
| M8 | The witness quietly degrades | `phi2/seed.py _gate()` falls back to the selftest when `host/` is absent | A missing oracle is a named refusal, never a fallback |
| M9 | Two executors of one contract give different verdicts | Python replay checks sha256, pexec does not | One contract, one verdict, gated |
| M10 | Repo hygiene | landed work left uncommitted, ~56 untracked scratch files, a stray file named `--run-probes` | Commit landed work; scratch lives in an ignored dir |
| M11 | Sync-by-copy in our own tooling | `~/.agents/AGENTS.md` copied/hardlinked into CLAUDE.md, .cursor rules, gemini; agents-memory `~/.agents/memory/.index/fts.sqlite` needs a full rebuild | The agents-store target: projections, not copies |

## 3. What holds (harvest, don't discard)

- **Lean core (isar-proofs):** confluence via parallel reduction; `cd` as normalizing strategy; Futamura with `Nontrivial` + `JonesOptimal` criteria; honest STATUS.md vacuity audit.
- **`KernelCategory.lean` is the mediator theorem in embryo:** for any two admissible kernels, `view_of₂ ∘ decode₁` is a `KernelHom` (from `decode_view`, `decode_eq`, `sound`). That's composition through a shared quotient with **no per-pair proof**. Check whether `ViewUnification.universal_factorization_theorem` already states it.
- **Engineering discipline:** spec-as-data, refuse-by-default naming the axis, independent witnesses, golden fixtures, frags per landed feature.
- **`sqlite_snake.html`:** data run as a program for real (game logic in an `AFTER UPDATE` trigger, rendering as a view).
- **`plex-cyberbrain/projections.sql`:** the projection catalog shape (language × encoding, parse/render, round-trip tests). Keep the shape; flip the defaults.
- **Koru rulings to reuse:** D7 "a handle, not a key" (slot+generation, stale access traps); D8 "an ordinal is a position, never a storable handle"; `std/proto` "affinity not coupling, sameness by NAME only, layout belongs to projections"; frag-oop "`ref(T)` = handle minted by an identity-interpreting plurality; values have no identity"; frag "a dedup key must be an identity, not a spelling."
- **living-software `kernel/schema.sql`:** entities/carriers/capabilities/applications/materialized_views. Same family; agents-store narrows it to append-only datoms + certificates.
- **agents-calendar:** stdlib CalDAV client, used as an independent scripted witness against the Radicale projection.

## 4. The core model (rules)

1. **Concepts/attributes are identified by name only** (koru proto rule), namespaced: `ical:DTSTART`, `md:title`, core `when`, `status`, `title`, `body`.
2. **Values are content-addressed** (no identity). **Entities get a minted ID** (ULID via `ids.mint()`), never reused, never derived from content or position.
3. **References between entities are datoms with `ref` value type**, indexed on `(a, v)` so they can be queried both ways. Never opaque fields buried in content.
4. **History is append-only:** `datom(e, a, v, tx, added)`; current state is a view; UPDATE/DELETE on `datom` abort via trigger.
5. **Kinds are structural over named attributes, multiplicative, and graded:** kind = required attrs + optional attrs + declared derivations. Fit may be graded for ranking and reading; **writes require real attributes or a declared derivation**, and derived values are marked derived and never written back.
6. **Adding an attribute is a revision** (a note becomes a task by gaining `status`). **Identity operations** are explicit transaction types with lineage: `evolve` (same id), `split`/`merge` (mint plus `wasDerivedFrom` edges), `correct` (sever + reason). Lineage vocabulary follows W3C PROV (`wasDerivedFrom`, `wasRevisionOf`, `alternateOf`, `specializationOf`).
7. **Wrappers (LAV):** each source maps losslessly into *its own namespace*. **Correspondences** between attributes are typed (`equal` / `refines` / `derivable` via lens) and carry a status `proposed → witnessed → proven`. Their closure gives the quotient.
8. **Mediators** = derived compositions (wrapper → correspondences → consumer), recorded as `exact` or `contained` (declared-lossy), each with a certificate.
9. **Capabilities** = registered `in_kind → out_kind`, mode `render` or `lens`. A pane = a path search over the capability graph.
10. **Default-deny:** an attribute is writable through a wrapper only if a correspondence or lens for it has status ≥ `witnessed` (POC policy; `proven` is required once Lean-certified lenses exist). Every refusal is recorded with its reason.

## 5. Minimal POC (agents-store v0, Python library)

### 5.1 Repo layout

```
agents-store/
  pyproject.toml                # name agents-store, MIT, py>=3.11, no runtime deps
  LICENSE                       # MIT
  README.md                     # what/why, demo steps
  AGENTS.md                     # guardrails = rules from §2 + §4, verification commands
  docs/MEGAPLAN.md              # this plan
  src/agents_store/
    __init__.py
    schema.sql                  # DDL below (idempotent)
    store.py                    # Store: open, mint, transact, current, history, kinds, refusals
    kinds.py                    # kind registry, membership (graded fit), derivations
    lineage.py                  # evolve/split/merge/correct + PROV edge helpers
    wrappers/__init__.py        # Wrapper protocol: get(entity)->repr, put(repr)->changes|Refusal
    wrappers/md.py              # markdown folder wrapper (frontmatter subset, stdlib only)
    wrappers/ical.py            # iCalendar VEVENT/VTODO serializer + subset parser (stdlib)
    capabilities.py             # registry + path search (BFS over in_kind→out_kind)
    pane.py                     # render(entity_id) -> HTML; serve(port) via http.server
    render/markdown_min.py      # stdlib minimal md→html (headings, paragraphs, lists, code, links)
    certify.py                  # property-test runner -> certificate rows (seeded, N configurable)
  plugins/radicale_agents_store/
    pyproject.toml              # GPLv3, depends: radicale==<pinned>, agents-store
    LICENSE                     # GPLv3
    radicale_agents_store/__init__.py   # Storage(BaseStorage) + Collection(BaseCollection)
  examples/
    demo.py                     # seed one entity, start pane, print Radicale config
    radicale.config             # [storage] type = radicale_agents_store, db path; auth none, localhost
  tests/
    test_store.py test_lineage.py test_kinds.py
    test_md_wrapper.py test_ical_wrapper.py test_lens_laws.py
    test_capabilities_pane.py
    plugin/test_radicale_plugin.py      # needs .venv with radicale; spins server on localhost
    plugin/test_agents_calendar_witness.py  # agents-calendar CLI against the running plugin
```

### 5.2 Schema (`schema.sql`, SQLite, WAL, foreign keys on)

```sql
CREATE TABLE IF NOT EXISTS entity (id TEXT PRIMARY KEY, created_tx INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS attr (
  name TEXT PRIMARY KEY,                 -- 'when', 'ical:DTSTART', 'md:path'
  value_type TEXT NOT NULL CHECK (value_type IN ('text','instant','int','bool','ref','json')),
  cardinality TEXT NOT NULL CHECK (cardinality IN ('one','many')),
  doc TEXT);
CREATE TABLE IF NOT EXISTS tx (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  agent TEXT, wrapper TEXT,
  op TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct')),
  note TEXT);
CREATE TABLE IF NOT EXISTS datom (
  e TEXT NOT NULL REFERENCES entity(id), a TEXT NOT NULL REFERENCES attr(name),
  v TEXT NOT NULL,                       -- JSON-encoded value; ref = entity id
  tx INTEGER NOT NULL REFERENCES tx(id), added INTEGER NOT NULL CHECK (added IN (0,1)),
  PRIMARY KEY (e, a, v, tx));
CREATE INDEX IF NOT EXISTS idx_datom_av ON datom(a, v);
CREATE TRIGGER IF NOT EXISTS datom_no_update BEFORE UPDATE ON datom BEGIN SELECT RAISE(ABORT,'datom is append-only'); END;
CREATE TRIGGER IF NOT EXISTS datom_no_delete BEFORE DELETE ON datom BEGIN SELECT RAISE(ABORT,'datom is append-only'); END;
CREATE VIEW IF NOT EXISTS v_current AS   -- latest assertion per (e,a,v) not retracted later
  SELECT d.e, d.a, d.v, d.tx FROM datom d
  WHERE d.added = 1 AND NOT EXISTS (
    SELECT 1 FROM datom r WHERE r.e=d.e AND r.a=d.a AND r.v=d.v AND r.tx > d.tx AND r.added = 0);
CREATE TABLE IF NOT EXISTS lineage (child TEXT NOT NULL REFERENCES entity(id), parent TEXT NOT NULL REFERENCES entity(id),
  kind TEXT NOT NULL CHECK (kind IN ('wasDerivedFrom','wasRevisionOf','alternateOf','specializationOf')),
  tx INTEGER NOT NULL REFERENCES tx(id), reason TEXT, PRIMARY KEY (child, parent, kind, tx));
CREATE TABLE IF NOT EXISTS kind (name TEXT PRIMARY KEY, required TEXT NOT NULL, optional TEXT NOT NULL DEFAULT '[]', derivations TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS certificate (id INTEGER PRIMARY KEY AUTOINCREMENT,
  tier TEXT NOT NULL CHECK (tier IN ('witness','proof')), subject TEXT NOT NULL,  -- 'wrapper:md', 'corr:12'
  ref TEXT NOT NULL, corpus TEXT, result TEXT NOT NULL CHECK (result IN ('pass','fail')), ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS wrapper (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, impl_ref TEXT NOT NULL, doc TEXT);
CREATE TABLE IF NOT EXISTS correspondence (id INTEGER PRIMARY KEY AUTOINCREMENT,
  a_from TEXT NOT NULL REFERENCES attr(name), a_to TEXT NOT NULL REFERENCES attr(name),
  kind TEXT NOT NULL CHECK (kind IN ('equal','refines','derivable')), lens_ref TEXT,
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','witnessed','proven')),
  certificate_id INTEGER REFERENCES certificate(id));
CREATE TABLE IF NOT EXISTS capability (id TEXT PRIMARY KEY, in_kind TEXT NOT NULL, out_kind TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('render','lens')), impl_ref TEXT NOT NULL, certificate_id INTEGER REFERENCES certificate(id));
CREATE TABLE IF NOT EXISTS mediator (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, target TEXT NOT NULL,
  path TEXT NOT NULL, exactness TEXT NOT NULL CHECK (exactness IN ('exact','contained')), certificate_id INTEGER REFERENCES certificate(id));
CREATE TABLE IF NOT EXISTS provenance (out_ref TEXT NOT NULL, in_refs TEXT NOT NULL, mediator_id INTEGER REFERENCES mediator(id), tx INTEGER REFERENCES tx(id));
CREATE TABLE IF NOT EXISTS refusal (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  wrapper TEXT NOT NULL, entity TEXT, attr TEXT, reason TEXT NOT NULL, payload TEXT);
```

Seed attrs/kinds: `title`(text,one), `body`(text,one), `when`(instant,one), `end`(instant,one), `status`(text,one; values `open|done`), `md:path`(text,many), `ical:UID`-free (UID ≡ entity id). Kinds: `event` {required:[when], optional:[end,title], derivations:[end := when+1h, marked derived]}; `task` {required:[status], optional:[when,title]}; `note` {required:[body], optional:[title]}.

### 5.3 Store API (`store.py`)
- `Store.open(path)` applies schema; `mint(tx) -> id`; `transact(ops, *, agent, wrapper, op='assert', note=None) -> tx_id` (ops = list of `(e, a, v, added)`; enforces attr type/cardinality; cardinality-one assert auto-retracts the prior value in the same tx).
- `current(e) -> dict`, `history(e) -> list[datom]`, `entities_of_kind(kind) -> list[(e, fit)]`, `refuse(wrapper, e, a, reason, payload)`.
- `lineage.evolve/split/merge/correct` build the tx + lineage rows (split/merge mint).
- `put_via(wrapper_id, e, changes)`: for each attr, check writability (rule 10) → assert or record a refusal; returns `(tx_id|None, refusals)`.

### 5.4 Markdown folder wrapper (`wrappers/md.py`)
- `get(root)`: for every entity of kind `note`, write `<root>/<md:path or slugified title>.md` with frontmatter (`id`, `title`, `when`, `status` when present; own minimal `key: value` subset) + body. Derived values are omitted.
- `reconcile(root)`: scan files (mtime + sha256 vs the last-seen table in memory/JSON sidecar in `.agents-store/`), parse; known `id` → diff to `put_via('md', …)`; rename with the same id → assert new `md:path`, retract old; no `id` → mint (create); unknown `id` → refusal; `id` edited → refusal; unparseable frontmatter → refusal (file untouched).
- Writable attrs via md: `title`, `body`, `status`, `when` (each requires a witness certificate from `certify.py`).

### 5.5 iCalendar wrapper + Radicale plugin
- `wrappers/ical.py` (stdlib): `to_vevent(e)`, `to_vtodo(e)` (UID = entity id, SUMMARY=title, DTSTART/DTEND=when/end, STATUS/COMPLETED from status, DTSTAMP from last tx ts), `parse(text) -> changes | Refusal` (folding, escaping, UTC `Z` times; `TZID`/floating → refusal in v0; `RRULE`, `VALARM`, `ATTENDEE` → refusal "not round-trippable in v0").
- Plugin `Storage(radicale.storage.BaseStorage)`: two collections per user, `calendar/` (entities with `when`, VEVENT) and `tasks/` (entities with `status`, VTODO); implement the BaseStorage/BaseCollection methods by reading Radicale's `radicale/storage/__init__.py` + `multifilesystem` as reference at implementation time (expected: `discover`, `move`, `create_collection`, `acquire_lock`, `verify`; collection `get_multi`, `get_all`, `has_uid`, `upload`, `delete`, `get_meta`, `set_meta`, `last_modified`, `etag`, `sync`). `upload` → `ical.parse` → `put_via('ical', …)`; a refusal raises a Radicale error that maps to HTTP 403/409 with the reason. Etag = sha256 of the rendered item. `create_collection`/`set_meta` for anything other than the two fixed collections → refuse. Lock = SQLite transaction plus a process-level lock.
- Pin: run `python -m pip index versions radicale` at implementation time; choose the newest 3.x whose release date is ≥7 days old; record it in the plugin pyproject.

### 5.6 Capabilities + HTML pane
- Registry seeded: `md→html` (render, `render/markdown_min.py`), `entity→card-html` (render: attribute table, relations both ways, lineage, kinds with fit), `event→html` (render: time block), `task→html` (render: checkbox state), `ical→attributes` (lens), `mdfile→attributes` (lens).
- `pane.render(e)`: compute the entity's kinds (with fit); for each kind/facet, BFS a path to `html`; render each section; facets with no path render a visible "no capability for <kind>→html" refusal (no crash). `pane.serve(port)` uses `http.server` on localhost: `/e/<id>` and `/` (list).

### 5.7 Lens-law certification (`certify.py`)
- Seeded random corpus (stdlib `random`, seed fixed, N=500 default) of entities within the writable attribute domain.
- md and ical wrappers: **GetPut** `put(get(s)) == no change`; **PutGet** `get(put(s, v)) == v` restricted to writable attrs. Pass → `certificate(tier='witness', result='pass', subject='wrapper:md'|'wrapper:ical')`, and the correspondences used get status `witnessed`. Fail → certificate with `result='fail'`; writes stay refused.

### 5.8 Acceptance criteria (POC is done when all hold)
- **A1** One entity with `title`, `when`, `status`, `body` appears as a VEVENT in `calendar/` and a VTODO in `tasks/` in **Thunderbird**, as a markdown file in the folder, and in the HTML pane.
- **A2** Moving the event in Thunderbird produces a new tx; after `md.reconcile`/`get` the frontmatter `when` updates; the pane shows the new time.
- **A3** Completing the task in Thunderbird sets `status=done`; md frontmatter and pane reflect it.
- **A4** Editing title/body in the md file changes SUMMARY in CalDAV (new etag), verified by Thunderbird refresh and by agents-calendar `list`.
- **A5** Renaming the md file keeps the entity id; `md:path` is updated; CalDAV items unchanged (same etag).
- **A6** Non-lawful edits are refused with reasons and the store is unchanged: adding an RRULE in Thunderbird (HTTP error, `refusal` row); editing `id:` in frontmatter (`refusal` row, file untouched).
- **A7** `history(e)` lists every change in tx order; UPDATE/DELETE on `datom` raise `datom is append-only`.
- **A8** `certify` passes GetPut/PutGet for md and ical on N=500 seeded cases; certificate rows exist; disabling a certificate makes the corresponding writes refuse.
- **A9** Adding `status` to a pure note makes it appear in `tasks/` (a revision, no mint); `split(e)` mints a new entity with a `wasDerivedFrom` edge visible in the pane.
- **A10** The pane renders every facet that has a capability path and shows an explicit refusal for one deliberately unregistered kind.
- **A11** The agents-calendar CLI (independent stdlib CalDAV client) lists, updates and deletes against the plugin, with etag semantics honoured (`If-Match`).

### 5.9 Verification commands
- `python3 -m venv .venv && .venv/bin/python -m pip install -e ".[acceptance]" -e plugins/radicale_agents_store` then `.venv/bin/python -m unittest discover -s tests -v` (303 at `main` HEAD; see `docs/AUDIT.md`)
- Windows: `.venv\Scripts\python` instead of `.venv/bin/python`
- `.venv/bin/python -m radicale --config examples/radicale.config` + `python examples/demo.py` for the manual Thunderbird check (A1–A6)

## 6. Phases after the POC

1. **Generated mediators (the "automatic systems programming" demo).** Add a second calendar source (`jsoncal` wrapper, a JSON export in its own namespace). Propose correspondences (structural/name match), certify, and generate a `mediator` so `jsoncal` items appear in CalDAV with no hand-written glue; write-back refused for non-round-trippable attrs; `provenance` rows on derived items. Acceptance: confirm 2 correspondences, then the items show in Thunderbird.
2. **Agent rules files as projections.** One record → `~/.agents/AGENTS.md`, `CLAUDE.md`, `.cursor/rules/user-rules.mdc`, `~/.gemini/config/AGENTS.md` via a projection (plain-file writer first; ProjFS provider second). Acceptance: edit in one place, the rest follow, and `sync.py`'s copy step can be deleted.
3. **agents-memory index as a maintained view.** Incremental upsert instead of rebuilding `fts.sqlite`; later, memory notes become store entities with the markdown as projection.
4. **More protocol projections:** CardDAV (contacts), WebDAV (files + properties), Maildir/IMAP (Message-ID as minted identity, `References` as lineage), HTTP content negotiation (one resource, many representations). ssh/curl/X11/FFI are transports (provenance + integrity, no lenses).
5. **Capability pane v1.** WASM component-model capabilities (typed WIT interfaces, sandboxed parsers); Kaitai-style declarative format specs + specialization for "unknown to the pane" formats.
6. **MCP + CLI surface** in the agents-* family shape once the schema settles.
7. **Koru store library (branch in `W:\src\koru`).** Entity/attribute model over `std/store` + `std/proto` (nominal attrs, minted handles, D7 generation checks); design input for the open "resource bridge" (identity across turns). Constraints: syntax is Lars's (bring questions, never invent spellings), regression tests first, check `pgrep -fl "run_regression|zig build"` before builds, POSIX/WSL toolchain. The Python POC's outputs become golden fixtures (independent witness).
8. **Formal certificates.** Lean: a generic mediating morphism between any two `Kernel`s (from `KernelCategory`), lens laws (GetPut/PutGet) and their composition; Futamura/Jones-optimality as the criterion that specialized mediators carry no hub overhead. Correspondence status `proven` is backed by these.
9. **Nextcloud as projections.** Calendar/Tasks via CalDAV already; Notes via WebDAV folder; Deck via its API wrapper. Nextcloud apps become views over the one store.

## 7. Parallel track: isar-proofs / phi2 (kill criterion)

- **Criterion:** by **2026-11-30**, phi2 produces native `assemble` for the full-src program (pass1 + `enc2_len`) under `gc=sweep` (decision 065 `byte_add` path, frag 0025 baseline: `enc2<'ret'>` = `c3` in 7.8s; `pass1` OOM). Miss → freeze phi2 (fixtures + frag + README), no new substrate.
- **Hygiene now:** commit the modified `host/gates/*`; move scratch (`_*.py`, `_blobs/`, `--run-probes`) to an ignored dir, after asking before any delete; keep golden fixtures as the oracle (`55d31ee`).
- **Harvest:** narrow README of what is proven; strip substrate/cosmology claims from public docs; state the generic mediating-morphism theorem (feeds §6.8).

## 8. The big aspiration ("you can just do things")

- One local store for a whole digital life: calendar, tasks, notes, mail, contacts, files, agent memory, board cards, repos metadata, all minted identities with typed relations and lineage.
- Every app is a capability or projection over it; no app owns data. Nextcloud, Obsidian, Thunderbird, phone, Cursor/Gemini rule files, lolaplex-board and cyberbrain become views.
- New formats arrive with a wrapper in their own terms; mediators to every existing consumer are **generated** from congruent quotient maps, certified, and fused by specialization (Jones-optimal), with no N² glue.
- A single capability pane opens anything there's a capability path for (a revival of Amiga Datatypes and OpenDoc, with the missing identity layer underneath), with sandboxed WASM parsers.
- Writes are lawful by construction: refused unless certified; every derived value carries provenance; every identity change is recorded lineage.
- Koru as the systems layer (forward flow, no pointers inside a turn, minted handles at the boundary); Lean certificates for the mediator and lens laws.

## 9. Reading list

- **Data integration / views:** Wiederhold 1992 "Mediators in the Architecture of Future Information Systems"; Halevy 2001 "Answering Queries Using Views: A Survey"; Lenzerini 2002 "Data Integration: A Theoretical Perspective" (LAV/GAV); Fagin et al. "Data Exchange: Semantics and Query Answering" (tgds); Clio papers.
- **Model management:** Bernstein 2003 "Applying Model Management to Classical Meta Data Problems"; Bernstein & Melnik 2007 "Model Management 2.0".
- **Categorical data:** Spivak "Functorial Data Migration"; CQL (Categorical Query Language) docs; Spivak & Kent "Ologs".
- **Bidirectional transformations:** Foster, Greenwald, Moore, Pierce, Schmitt "Combinators for Bidirectional Tree Transformations" (lenses); Bohannon et al. "Boomerang"; Bancilhon & Spyratos 1981 "Update Semantics of Relational Views".
- **Provenance / lineage:** Green, Karvounarakis, Tannen 2007 "Provenance Semirings"; W3C PROV-DM / PROV-O; OpenLineage spec; Buneman et al. "Why and Where".
- **Identity / stores:** Datomic information model (datoms, EAVT); koru `docs/OUTSTANDING_DESIGN_DECISIONS.md` D7/D8; koru concepts `frag-type-system-design`, `frag-oop-is-a-store-encoding`, `frag-a-proto-is-a-leaf-bundle-not-a-struct`, `frag-a-dedup-key-must-be-an-identity-not-a-spelling`; Rust `slotmap` / Bevy `Entity` (generational indices).
- **Filesystems / documents:** Gifford et al. 1991 "Semantic File Systems"; BeFS attributes; WinFS post-mortems; OpenDoc history; Amiga Datatypes; Windows Projected File System docs; WinFsp.
- **Web / protocols:** Fielding's dissertation (resource vs representation); RFC 4791 (CalDAV), RFC 5545 (iCalendar), RFC 6352 (CardDAV), RFC 4918 (WebDAV); Radicale storage plugin docs.
- **Partial evaluation / synthesis:** Jones, Gomard, Sestoft "Partial Evaluation and Automatic Program Generation"; Augustsson "Djinn"; MicroHs (combinator self-hosting baseline).
- **Prototype theory (graded kinds):** Rosch "Principles of Categorization".
- **Own material:** isar-proofs STATUS.md (vacuity audit), `KernelCategory.lean`, `Futamura.lean`, frags 0014/0017/0019–0025, decisions 064/065; `isa-physics/docs/session/ARCHAEOLOGY_TOOLCHAIN.md`; `sqlite_snake.html`; `plex-cyberbrain/{bootstrap,projections}.sql`; living-software `kernel/schema.sql`; bend-probe `FINDINGS.md` (FFI boundary weakness: forged `Rfl` → silent `nan`).

## 10. Risks and trade-offs (stated, not absorbed)

- **Writing the store twice** (Python POC, later koru) costs less than another substrate chosen before validation.
- **Radicale GPLv3:** the plugin sub-package is GPLv3; the core stays MIT. The Radicale storage API is internal-ish and can change between versions; mitigated by pinning and tests.
- **iCalendar is lossy** for relations, recurrence and timezones in v0. Refused, not approximated. Recurrence/TZ is the first likely v1 extension.
- **The `witnessed` write policy** is weaker than `proven`; accepted for the POC, tightened once Lean lens certificates exist.
- **Vocabulary agreement is still real work.** Typed correspondences make it local and incremental; they don't remove it.
- **The general pane loses the polish of single-purpose apps.** Mitigated by allowing specialized views as capabilities.
- **Running two tracks** (store + phi2) splits attention. Bounded by the 2026-11-30 kill criterion.

## 11. Execution on approval

- **Step 0 (on approval):** create `C:\Users\fabi0\repos\agents-store` (git init, no push), write `docs/MEGAPLAN.md` (this plan), `README.md` stub, `LICENSE` (MIT), `AGENTS.md` (guardrails §2/§4 + verification §5.9), `.gitignore` (`.venv/`, `.agents-store/`, `__pycache__/`, `scratch/`); register the project in agents-memory (`register_project` slug `agents-store`, role "one identity, many lawful projections (store + wrappers + mediators)", stack "Python 3.11 stdlib, SQLite, Radicale plugin", status active) and run sync; initial commit.
- **POC P1–P5** (proceed in order once you say go): P1 store + schema + lineage + kinds (A7, A9) → P2 md wrapper + certify (A5, A6-md, A8) → P3 ical wrapper + Radicale plugin (A1–A4, A6-ical, A11) → P4 capabilities + pane (A10, A1-pane) → P5 manual Thunderbird pass, frag-style write-up in `docs/`, commit.
