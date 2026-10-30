# Referenced content supplement

This is a **scoped historical source recovery** for IDs missing or inconsistent in the checked-in merged data archive. It is not a claim that the older records were verified against the currently installed game client, and it never modifies data/current.zip.

The entries in data/supplements/referenced_content.json include the original historical source path and Git blob SHA. They are partitioned into three actions:

- add_if_absent (132): add an old record only if the current table lacks that ID.
- backfill_missing_fields (74): fill only absent keys in an existing record; never overwrite current values.
- review_conflict (41): return current values and historical candidates side by side, with no automatic replacement.

Historical sources: the previous Pak layers in this same repository. The target client archive SHA-256 is pinned in the supplement. A requested reward ID, 19589, has not been verified in the checked July or August sources and is intentionally unresolved.

Run from repository root (Python 3.10+, standard library):

~~~powershell
python tools/content_supplement.py verify
python tools/content_supplement.py export --output build/referenced_content_resolved.json
python tools/content_supplement.py get --table DIALOGUE_CONF --id 303010000
~~~

The export includes a scoped resolved_records array, a review_candidates array, and unresolved items. It retains source attribution per record, including original source-path Git blob fingerprints. This is not an automatic whole-game overlay or a replacement for original decoding. Some historical dialogue fields are optional; story flag editor labels alone do not establish action semantics. Condition combinators, exact world-location identity, and required gameplay receipts remain separate evidence tasks.
