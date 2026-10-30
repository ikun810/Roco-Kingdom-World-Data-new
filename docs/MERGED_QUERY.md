# 在本地直接查询 PC 1.111.0.177 的合并配置数据

仓库的 `main` 仍将 2026-07-16 原始五层配置保留为历史资料。新版 `1.111.0.177 (229314)` 的完整 FModel 导出数据只保存在持有者本地，并非公共 GitHub 发布物。你可以直接用 `tools/merged_query.py` 在原始 ZIP 中查询，不需要解压、合并 Pak，也不需要创建大型 SQLite。

## 快速开始（Windows PowerShell）

需要 Python 3.10+，且克隆当前仓库。以下 `D:\Data\Bin(1).zip` 只是命令里的**示例路径**：请替换为你实际存放 ZIP 的位置。要求其 SHA-256 与仓库已登记的原始导出一致。

```powershell
# 已登记表清单：只读 GitHub 中的元数据，无需本地游戏 ZIP
python tools/merged_query.py --manifest docs/snapshots/pc-1.111.0.177-229314.json tables --filter SEASON

# 查询 S4 赛季的 ID=4
python tools/merged_query.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --source 'D:\Data\Bin(1).zip' get --table SEASON_CONF --id 4

# 限定赛季领域搜索名称；输出最多 10 条命中摘要
python tools/merged_query.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --source 'D:\Data\Bin(1).zip' search --domain season --query 月涌 --limit 10

# 跨七个常见领域搜索名称（pet / skill / map / task / item / npc / season）
python tools/merged_query.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --source 'D:\Data\Bin(1).zip' search --query 月涌 --limit 20

# 读取精灵配置里的指定 ID（3001 为当前快照中一条真实记录）；会显示单条原始记录，应保留在本地终端
python tools/merged_query.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --source 'D:\Data\Bin(1).zip' get --table PETBASE_CONF --id 3001
```

调用时，`--manifest` 和 `--source` 参数需要写在 `tables` / `get` / `search` **之前**。如需指定 `BinData` 类型的同名表，可使用 `--table BinData/XXX`。直接搜索只使用已有 `tools/effective_search.py` 的名称白名单，不扫描剧情正文、长描述或资源路径；`get` 明确按 ID 请求时才会返回单条完整记录。所有命令均不往游戏客户端或远程服务器写数据。

## 校验范围

- 查询前校验输入 ZIP 的整体 SHA-256，拒绝与登记快照不一致的 ZIP；目录输入则在每次打开表时检查该文件的原始及语义 SHA-256。
- 每次查询表时均验证记录数、记录 ID 指纹、观察字段清单。查询只读取需要的表，不加载另外 869 张表的数据正文。
- `tables` 不传 `--source` 时仅浏览版本清单元数据，不声称现场验证本地 ZIP。如传 `--source`，仍会执行 ZIP 指纹验证。
- 默认不读取 `BinDataCompressed_ROW` 国际服覆盖变体。它独立保留在快照清单，不与普通 `BinDataCompressed` 合并。
- FModel 合并导出的每张表仍可能采用未核实的 Pak / Schema 来源，工具每次返回 `pak_mount_order_verified=false` 与 `per_table_schema_origin_verified=false`。它不会修改或“修复”有争议的字段。
- 工具不提供内容上传命令；对外发布游戏原文或完整 ZIP 须独立确认授权。CI 只能在合成样本及公开元数据上运行，不能访问用户本地原始 ZIP。

## 后续补齐 Schema 来源

PR #7 与 PR #8 已保留 33 张表中 56 个历史未见字段的完整元数据清单，请参考 [`pc-1.111.0.177-release-qa.md`](reports/pc-1.111.0.177-release-qa.md)。无需重复导出全部 870 张表；下一轮只需优先确认 `PETBASE_CONF`、`NPC_CONF`、`MODEL_CONF` 和 `ACTIVITY_SEASON_SPRINT_CONF` 在客户端实际选用的同版本 `.non`。对这些表的来源核实将独立推进，不影响本地读表使用。

在确认原始数据再分发范围之前，仓库**不会**将本地 ZIP 自动提交到 `main`，也不能把此候选版本称为已发布的完整版数据库。
