# frags — evidence write-ups

Numbered `NNNN-kebab-name.md`, same convention as isar-proofs/docs/frags.
Every non-trivial claim gets one: what was measured, exact command, commit
(`git rev-parse HEAD`), output summary. No claim without a frag or a test
name pointing at it.

Template:

```
# NNNN <name>

- commit: <rev>
- task: T<id> (or "exploration")
- claim: <one sentence>
- evidence: <command> → <key output>
- limits: <what it does NOT establish>
```
