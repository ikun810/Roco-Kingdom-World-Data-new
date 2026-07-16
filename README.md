# Roco Kingdom World Data

Decoded Roco Kingdom configuration and protocol data, maintained as a rolling repository.

Current snapshot: `2026-07-16`

Historical snapshots are available through Git tags:

- `2026-05-21`
- `2026-05-24`
- `2026-07-16`

The repository keeps files from each pak chunk separated, so same-path files from different patch layers are not merged.

Pak folders:

- `pakchunk4-WindowsNoEditor`
- `pakchunk4-WindowsNoEditor_0_P`
- `pakchunk4-WindowsNoEditor_1_P`
- `pakchunk4-WindowsNoEditor_2_P`
- `pakchunk4-WindowsNoEditor_3_P`

Each pak folder contains the decoded structure: `Bin/`, `Config/`, `PB/`, and `_logs/`. Audio and video assets are intentionally excluded.

When a data file requires a schema from an earlier pak layer, the schema is used only for decoding and its source is recorded in `_logs/schema_usage.csv`.
