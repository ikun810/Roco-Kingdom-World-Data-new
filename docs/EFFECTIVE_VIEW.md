# 单一候选有效视图（2026-07-16）

本仓库的 Pak 目录为基础包及递进补丁。**不应把所有 Pak 层都完整导入一份“当前有效数据库”**：对于相同的逻辑路径，补丁层的配置文件是整体替换，不是将每层 `RocoDataRows` 按 `id` 合并。

## 覆盖策略

采用 Unreal 常见文件名优先级作为**候选假设**，从低到高：

```text
pakchunk4-WindowsNoEditor
pakchunk4-WindowsNoEditor_0_P
pakchunk4-WindowsNoEditor_1_P
pakchunk4-WindowsNoEditor_2_P
pakchunk4-WindowsNoEditor_3_P
```

- 同一个 `Bin/BinDataCompressed/XXX.json` 或 `Bin/BinData/XXX.json`，选择**最高层存在的整份文件**；不合并不同层的行。
- 高层没有该文件，则继承低层版本。`_3_P` 仅有少量文件，单独读取它不是完整数据。
- 不同语言的本地化文件按完全相同的逻辑语言路径覆盖；`zh_CN` 和 `zh_Hans` **不能**随意当作同一个语言目录。
- 源仓库保留五层原始历史；有效视图只记录每张表的来源路径、SHA-256、记录数、字段和补丁覆盖链。
- 索引不包含游戏原始正文；单条查询时才读取被选中表的数据，并验证哈希。

**限制**：以上排序符合 Unreal 常见命名模式，但尚未得到这款游戏运行时实际 Pak 挂载顺序的独立证据。产物始终带 `pak_mount_order_verified=false`，称为 *candidate effective view*。没有提供比实际客户端优先级更强的权威结论。`schema_source_layer` 若未知则保持 `null`；Schema 来源可另查各层 `_logs/schema_usage.csv`，不能直接用最新 Schema 覆盖旧层的解码证据。

## 直接使用

Python 3.10+ 标准库。根目录执行：

```powershell
python tools/build_catalog.py --root . --output build/catalog_20260716.json --summary build/catalog_summary_20260716.json --strict
python tools/effective_view.py build --catalog build/catalog_20260716.json --output build/effective_view_20260716.json --summary build/effective_summary_20260716.json
python tools/effective_view.py get --root . --view build/effective_view_20260716.json --table SEASON_CONF --id 3
python tools/effective_view.py find --root . --view build/effective_view_20260716.json --table SEASON_CONF --field s_title_subtitle --contains 幻梦
```

必要时通过 `build --order <基础层> <覆盖层...>` 显式指定从低到高的顺序；也不会自动标记为已核验。`get` 和 `find` 只读取所需表，不构建庞大的全量 SQLite。

## 报告解读

- `effective_table_kinds`：最终候选视图包含多少种不同的数据表（同名跨层只算一次）。
- `effective_rows`：只累计**被选中的最高优先级完整文件**中的行，不等于游戏实际生效独立实体数量。
- `source_file_copies`：五层中所有同名副本数，供历史审计，不等于需要导入的表数。
- `not_selected_source_rows`：被舍弃的较低优先级表文件中的行数总和，**不等同**“重复实体数”。
- `selected_tables_by_layer`：最终采用的各层源文件数量；确保底层缺失的继承逻辑没有丢失。

GitHub Actions 的 `Build July 2026 data catalog` 工作流会执行真实数据扫描，并上传 `effective_view` 与 `effective_summary` 作为有期限的构建产物。仓库不保存派生 SQLite 和未确认可再分发的数据副本。
