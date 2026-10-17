# Backlog — post-POC

POC passed (tag `poc-v1`, 2026-10-17). Not cards yet; seed for the next
planning round. Each needs evidence of a real need from the POC before
promotion.

**Promoted to cards:** correspondence matching + generated mediators
(T13–T16, MEGAPLAN §6.1).

- **ProjFS / filesystem adapter**: entities-with-body as files-on-demand
  (Windows-only; pair with T05 folder adapter learnings).
- **WebDAV wrapper**: file-level protocol sibling to folder adapter.
- **CardDAV, IMAP/Maildir wrappers**: contacts; mail (Message-ID minted IDs +
  In-Reply-To lineage are PROV-shaped already).
- ~~**Correspondence matching (`Match`)**~~ → T14.
- ~~**Generated mediators**~~ → T15/T16 (attr-level materialization;
  render-path mediation already in `mediator.py` from T09).
- **Glue specialization**: generated composite paths cached in `mediator`;
  later, fuse paths to remove hub materialization (Jones-optimality as the
  bar, cf. isar-proofs Futamura.lean).
- **WASM component-model sandbox** for untrusted capability impls (codec
  parsers are attack surface).
- **Solid-style vocabulary publishing**: export attr namespace + kinds so
  external tools can align without a private agreement.
- **koru systems layer** (consumer-found): minted IDs exist there (D7
  generational handles); cross-process identity ("resource bridge") is the
  upstream-open problem — revisit once POC measures the real requirements.
- **phi2 native-cogen track**: separate repo, deadline 2026-11-30; this
  backlog does not gate it.
