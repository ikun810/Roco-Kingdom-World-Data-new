# Referenced content supplement

**2026-10-31 raw-source follow-up:** The four requested tables can now be redecoded from original binary assets. Use `python tools/raw_content.py export --output-dir build/raw-content` for 659 scoped records: 255 verified from raw sources plus 404 historical recoveries, with the original 171 binding reviews and reward 19589 addressed in that output. See [Raw configuration recovery](RAW_CONTENT.md) for provenance and remaining runtime limitations. The commands and counts below describe the preserved historical-only recovery path.

This is a scoped recovery from original historical Pak exports. It preserves the pinned `data/current.zip` and keeps historical provenance separate from current-client validation.

## Export recovered content

Run from the repository root with Python 3.10+:

~~~powershell
python tools/content_supplement.py verify
python tools/content_supplement.py export --output build/referenced_content_resolved.json
python tools/content_supplement.py get --table DIALOGUE_CONF --id 303010006
~~~

The main supplement contains **658** source entries:

| Operation | Entries | Export behavior |
| --- | ---: | --- |
| `add_if_absent` | 413 | Add the historical row only when the current archive lacks its ID. |
| `backfill_missing_fields` | 74 | Fill only explicitly listed absent keys, preserving all existing values. |
| `review_conflict` | 171 | Return current and historical values for review; do not replace current fields. |

The export therefore has **487 recovered records/field backfills**, **171 review candidates**, and **1 unresolved ID**, `REWARD_CONF/19589`. These are separate categories; 487 does not mean 487 current-client values were verified. The output is a scoped subset, not a whole-game database.

Each source entry retains its original Pak path and Git blob fingerprint. Verification checks the current archive SHA-256, historical file bytes and exact historical record before recovery. Missing optional fields are not fabricated.

## Dialogue successors and choices

The original 101 missing dialogue IDs were entry points, not complete dialogue chains. Following only explicit `DIALOGUE_CONF.next_dialog_id`, `DIALOGUE_CONF.select_ids`, `SELECT_CONF.select_next_dialogue` and `SELECT_CONF.notimes_dialogue` visits **512 nodes** and **495 edges**:

- **382 dialogue rows** are absent from the current archive; the supplement now contains all of them, including **281 additional successors**.
- **130 selector rows** already exist. Their non-text fields match the selected historical source, but all 130 `text` values differ; 36 current values are empty. They remain review-only candidates.
- No target of these four observed reference fields remains without a source row. This is structural coverage, not proof of runtime reachability, correct condition evaluation or a fully playable story.

The original 41 review candidates are retained alongside the 130 newly discovered selector-text candidates. The increase to 171 reflects a wider, explicitly linked scope.

~~~powershell
python tools/dialogue_closure.py --output build/dialogue_reference_audit.json
~~~

The roots, selected historical files and their fingerprints are recorded under `dialogue_reference_scope` in the supplement. Existing current rows always take precedence during traversal; the tool does not silently fill their graph fields from history. Use `--expanded-output build/expanded.json` to prepare a new supplement for review; the tool refuses to overwrite source data.

## Optional bonus-story fields

The separate `optional_story_content.json` restores **251 absent fields in 75 rows** of `SEASON_BONUSCATCH_STORY_CONF`. The historical and current tables have identical IDs and `text` values. The recovered fields cover initial NPC/bubble/backdrop references and **64 option objects** in 30 option arrays.

~~~powershell
python tools/content_supplement.py --supplement data/supplements/optional_story_content.json verify
python tools/content_supplement.py --supplement data/supplements/optional_story_content.json export --output build/optional_story_resolved.json
~~~

The source contains no successor field. Bubble-dialogue resources and NPC-group resources are not completely established by this export. The 75 rows are optional source recovery, not 75 certified playable events or a prerequisite for mandatory story progression.

## Supporting source evidence

Checked-in evidence is in [data/evidence](../data/evidence). Reproduce it without network access:

~~~powershell
python tools/content_binding_audit.py --repo . --output build/content_binding_evidence.json
python tools/reward_source_evidence.py --repo . --output build/reward_source_evidence.json
python tools/source_semantics.py --repo . --output-dir build/source-evidence
~~~

- **Binding audit:** All 171 candidate fields are stable across historical layers containing the corresponding ID. The original four letters and three tasks have 27 differing text leaves, all present in the current Chinese string pools. Only 9 of 130 historical selector strings occur in the current pool, and those are generic phrases. Pool membership does not prove the current record-to-index binding. Task numeric structures are retained; entire `task_condition` or `go_guide` arrays must not be replaced just to fix text.
- **Rewards:** 114 named historical reward candidates contain 219 components and 92 unique numeric identities. Their identities are linked by `(Type, Id)` to same-source tables, with original counts and weights. The missing-content request names 115 problem IDs, including 19589; it does not name the remaining, originally passing member of the reported 116-template set. This evidence does not invent that ID or authorize reward settlement.
- **Enums:** 30 original enum definitions contain 787 symbol/value pairs. Candidate mappings to configuration fields are in a separate coverage report. Schema fields declare integers, not enum bindings. Seven observed task-condition values are absent from the historical enum (26 slots), and 28 slots omit `type`; omitted values are not assigned zero. Operand order, whole-array AND/OR and runtime actions remain unverified.
- **Scene identity:** 17 source entry relationships retain `scene_res_id`, content IDs and full area rows. The mainland resource 10003 and academy resource 10018 both have `scene_id=103`; a lookup keyed only by `scene_id` conflates them. This is source identity evidence, not a complete downstream map assignment.

See [the maintenance findings and minimum remaining source request](reports/referenced-content-maintenance-20261031.md).
