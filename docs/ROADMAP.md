# Roadmap after v0

v0 is the POC in `docs/MEGAPLAN.md` §5 plus the §6.1 mediator work (T13–T16). It passed
the manual check on 2026-10-18 (`docs/AUDIT.md`). Freeze it as-is: v0 takes fixes only.
The "actual" line starts here. Every item still needs evidence of a real need before it
becomes a card (BACKLOG rule).

## 1. Multiple byte encodings

An entity value has one meaning and many carriers. Encodings become first-class records
(name, carrier type, lossy flag, spec). A value can be rendered to any lossless encoding
and parsed back. A lossy encoding is a declared `contained` projection, never `exact`.

Prior art in `Cypoe/isa-physics` (main `fa7275e`):
- `plex-cyberbrain/projections.sql`: the `encoding` table (`raw-binary`, `utf8`, `ascii`,
  `msgpack`, `json`, `binsparse-coo`, `png`, `jpeg`, `f32-ieee754`, each with
  `is_lossy`), kept separate from `language`.
- `plex/core/bytechunk.py`: lossless byte ↔ 4×4 nibble chunk ingest/emit (RFC §2.2).
- `plex/lib/views/{ascii,hex,utf,graph}.py`, `docs/RFC/plex_views.py`: stateless views
  over one byte carrier.
- `docs/RFC/plex_core.py`: the `.plex` container round-trip.

Keep the shape and flip the defaults (MEGAPLAN M5). `projections.sql` declares
lawfulness with `DEFAULT 1`; here every encoding pair needs a certificate.

## 2. Schemas

Typed attribute schemas per wrapper namespace, in JSON Schema, so that external tools
can validate a projection without the store. They're generated from the registry
(`registry.py`, `kinds.py`), not written by hand. `jsoncal` (T13) is the first consumer.

Prior art: `plex-sql/plex_sql_schema.py` and `plex_sql_types.py` (typed column
encoders). Don't copy their *positional* identity ("position = reference"). That's
misstep M6. Identity stays minted.

## 3. Semantics

A language is a semantic projection over an encoding: what the symbols mean, distinct
from how the bits are arranged. Correspondences (`match.py`) gain a semantic level:
`equal` / `refines` / `derivable` relative to a declared language, not only to a name.

Prior art: the `language` table in `plex-cyberbrain/projections.sql` (s-expression,
m-expression, …), `plex/lib/dialects/{lisp,mexpr,c,quantity}.py`,
`plex-cyberbrain/m-expression-view.sql`.

## 4. Composable, chainable results (structural and computational)

A derived value (a mediator output, a query result, a computation) is itself an entity
with provenance. That lets results chain: the output of one certified derivation is the
input of the next, and the certificate composes. Structural results (renames,
projections, joins) and computational results (evaluations) use one provenance model
(`provenance` rows, `mediator_id`, `tx`).

Prior art (demos, with stated limits):
- SQL: `sqlite_snake.html` (game logic in an `AFTER UPDATE` trigger, rendering as a
  view, cited in MEGAPLAN §3); `plex-cyberbrain/bootstrap.sql`, `stdlib.sql`,
  `projections.sql`; `cosmology/isar_sqlite.py` (a program as a relation evaluated by
  joins); `plex-sql/` (`demo_gpu_sql.py`, `hybrid_engine.py`). Their benchmark and
  "trivial on GPU" claims are unmeasured here (M3).
- Plain-Python plex toys: `docs/RFC/plex.py`, `plex_core.py`, `plex_views.py`,
  `plex_eval.py` (JOIN/NORM/chain; JOIN is "simplified: element-wise addition mod 4"),
  `plex_bundle.py`, and the chain scripts in `docs/RFC/chain/` (`plex_isar_pipeline.py`,
  `plex_views_bundle.py`, `plex_semantic_system.py`; usage in
  `docs/RFC/chain/USAGE.md`). There's also the `isar_plex.py` monolith.

Bar: a chain of two certified derivations whose composite certificate a test checks.
That's MEGAPLAN §6.8's mediating-morphism theorem applied once.

## 5. Identity events (v1 record type)

A new kind, `identity-event`, for signed, hash-chained identity records (inception,
rotation, interaction seals, witness receipts, checkpoints), per
`Cypoe/isa-physics` `docs/RFC/PHI_IDENTITY.md`:
- the entity id stays minted; the event's SAID is an attribute, and the chain link is a
  `ref` to the prior event entity;
- bodies are stored byte-exact (canonical JSON). Signatures are qualified primitives; no
  secrets;
- the lolaplex-board DID event log is the first import source (ULID row ids, canonical
  JSON). Import is lossless or refused.

## 6. Order

1 → 2 run together (encodings need schemas). 3 builds on both. 4 needs the certificate
composition from MEGAPLAN §6.8. 5 is independent and can start as soon as the board's
chain integrity v2 lands.
