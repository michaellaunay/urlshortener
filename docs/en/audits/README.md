# Audits

One file per pass, named `YYYYMMDD_<subject>.md`, **self-contained**:
it carries its own preamble (who, how, what scope, what limits), its
findings with their evidence, the state of each fix, and the decisions
left to the maintainer.

An audit is never rewritten afterwards. A finding revisited later gets
a new pass that cites the previous one.

| Date | Pass | Verdict |
| --- | --- | --- |
| 2026-08-22 | Internal security audit | 1 high, 3 medium, 6 low, 4 accepted risks — every fixable finding fixed |
| 2026-08-22 | External audit (ChatGPT) | 4 P0, 4 P1, 5 P2, 1 P3 — trains 0002 to 0010, one accepted risk |
| 2026-08-22 | External audit, second pass | "Broadly solid" — 3 fixes (trains 0012 to 0014), 2 accepted risks, 3 decisions pending |

## Language parity

The project's convention is that `docs/fr` and `docs/en` mirror each
other. **Both reports are written in French only**; the full English
translation is pending. Stated here rather than hidden, because a
missing mirror an English reader discovers by clicking a dead link is
worse than one the index warns about.

The reports themselves live in
[`docs/fr/audits/`](../../fr/audits/README.md). Everything they
concluded is reflected in `CHANGES.txt`, which is bilingual by being
written in English.
