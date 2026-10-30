# Referenced content chain maintenance

> For agentic workers: follow the existing source recovery design in `docs/CONTENT_SUPPLEMENT.md`; use systematic debugging and verification before completion.

**Goal:** Recover the source records transitively referenced by the reported content gaps, and preserve evidence for the remaining conflicts.

**Architecture:** Keep the pinned current archive and historical Pak layers immutable. Extend the existing additive supplement with reachable missing dialogue records and review-only selector text candidates. Keep optional bonus-story fields in a separate compatible supplement. Export original enums, reward identities, and scene relations as source evidence, not executable game rules.

**Tech stack:** Python 3.10+, standard library, existing unittest and GitHub Actions workflows.

**Spec:** The user's supplied required-source-fields r5 list and `docs/CONTENT_SUPPLEMENT.md`.

## Constraints and decisions

- Continue the already authorized repository maintenance; preserve the original client archive and per-layer files.
- Follow only explicit `next_dialog_id`, `select_ids`, `select_next_dialogue`, and `notimes_dialogue` edges. Do not infer edges from names or ID ranges.
- Existing rows win over historical rows. A graph audit establishes structural reference coverage, not condition semantics or runtime reachability.
- Review candidates remain unapplied by default. Current locale text presence corroborates a historical string but does not prove its current binary binding.
- Preserve raw reward counts; descriptions are not an authority for changing numeric values. Missing reward 19589 stays blocked.
- No gameplay receipts, M1-wide mappings, condition operand rules, or bonus-story successors are invented.

## Tasks

- [x] Implement `tools/dialogue_closure.py` and behavioral tests for branches, cycles, missing targets, current-row precedence, and text conflicts. Generate the extended additive supplement and a reproducible graph audit.
- [x] Add the independently verified 75-row optional-story supplement; use the existing resolver to verify all source records and missing-key-only backfills.
- [x] Integrate reproducible conflict, reward, enum and source-identity evidence. Keep the three downstream coordinate anchors explicitly scoped.
- [x] Update source recovery documentation, the minimum raw-source request, and real-data CI checks.
- [ ] Run the existing tests and actual source verification, review the resulting diff, submit and merge through GitHub after checks pass.

## Review focus

- Cyclic dialogue choices must terminate and preserve all distinct incoming edges.
- Current rows must not be replaced by historical records during graph traversal or export.
- Target archive or source fingerprint drift must reject recovery.
- Historical source availability must not be reported as current-client validation.
- Optional field restoration must not imply a complete executable story chain.

## Progress

Baseline: 164 existing tests passed on the isolated maintenance branch.

Investigation: 101 original dialogue roots traverse 512 observed nodes (382 missing dialogue rows and 130 existing selectors); all target IDs have a historical source. All 130 selector texts differ from the historical source, including 36 empty strings. These are review candidates, not automatic replacements.

Independent final review found ancillary reward source fingerprints needed to be pinned, and a colliding optional runtime-map output needed an explicit input guard. Both were reproduced and fixed with targeted regressions. Ruling: treat original input preservation as part of maintenance correctness even for the optional output path; no raw source may be overwritten.

Runtime semantics, the historical/current binding distinction and unseen downstream locations remain unverified by design and are reported as limitations, not dismissed as completed work. No additional broad gameplay tests were introduced.
