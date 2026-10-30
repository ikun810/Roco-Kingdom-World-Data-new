# PC 1.111.0.177 (229314)：FModel 合并导出候选快照

此工具用于读取用户自行合法取得的 FModel `Bin/` 合并 JSON 导出（支持 `.zip` 或目录），生成**仅元数据**的版本清单。其用途是帮助版本审计、查找字段变化及比较历史文件；它**不对游戏客户端动手，也不解密 Pak**。

## 已确认的输入和限制

- 采集标记：2026-10-30；用户报告的 Windows PC 客户端版本号 `1.111.0.177 (229314)`。
- 上传 `Bin(1).zip` 的 SHA-256 为 `9fa5d0cecd25ac32335f3d6e9624e49353e5f357f14504c9cdd032002fd1b515`。这是**原始上传 ZIP 的指纹**，不是服务器来源证明。
- ZIP 中 `BinConf/` 870 份、`BinDataCompressed/` 普通配置 870 份、`BinLocalize/` 571 份、国际服 `BinDataCompressed_ROW/` 三份。没有 `BinData/`。
- 表中的普通记录合计 **675,341 条**；50 张表的 `RocoDataRows` 为空。文件可解析且没有缺失同名 Schema。
- **107 张表观察到 JSON 记录字段不包含在本次同名 `BinConf` 的声明字段中**（包含 `SEASON_CONF`、`PETBASE_CONF`、`ACTIVITY_CONF`）。这属于需要调查的**Schema 与合并导出不一致警告**，不能当作源数据完全一致的证明。可能与 FModel 跨层选择 Schema 有关，未作出定论。
- `SEASON_CONF` 4 条，包含 S4「月涌狂想」。用户确认成功打开的 `SEASON_CONF.bytes` 来自 `pakchunk4-WindowsNoEditor_3_P.pak`，但未提供所有表的原 Pak 来源。
- 另有 381 条客户端 Pak 路径清单。清单未提供文件大小、哈希或挂载优先级，因此不能据此重建所有配置表的逐层归属。

**已发布**的 `docs/snapshots/pc-1.111.0.177-229314.json` 只有名称、字段名、记录数量、哈希和 Schema 检查警告，不包含精灵、任务、对白等记录正文。原始 ZIP **不随 GitHub PR 提交**，避免未经审查的游戏资源再分发。

## 本地复现元数据清单

在仓库根目录运行（Python 3.10+，标准库）：

```powershell
python tools/merged_snapshot.py snapshot --source 'D:\Data\Bin.zip' --game-version 1.111.0.177 --build-number 229314 --capture-date 2026-10-30 --season-source-pak pakchunk4-WindowsNoEditor_3_P.pak --output build/pc-1.111.0.177-229314.json --strict
```

`--source` 也可以指向包含 `BinConf/`、`BinDataCompressed/`、`BinLocalize/` 的目录或其上层 `Bin/`。工具不会从 ZIP 解压写出文件，默认完全只读，并会拒绝路径穿越、重复逻辑路径、危险软链接或超限文件。`--strict` 对结构错误或缺少 Schema 返回非零状态，但观察到多余字段仅作警告。

清单为 `roco_merged_snapshot_v1`：包含文件 SHA-256、语义行哈希（键排序后的 `RocoDataRows`）、记录 ID 集合哈希、字段名、匹配 Schema 的哈希、语言表摘要、ROW 单独隔离信息以及异常列表。JSON 文本排版方式不同但**解析值相同**时，语义行哈希相同；哈希不同不代表一定发生了真实游戏内容变更，解码 Schema 的差异也可能影响结果。

## 对比 2026-07-16 历史候选有效视图

先运行现有仓库工具生成七月元数据：

```powershell
python tools/build_catalog.py --root . --snapshot 2026-07-16 --output build/catalog_20260716.json --summary build/catalog_summary_20260716.json --strict
python tools/effective_view.py build --catalog build/catalog_20260716.json --output build/effective_view_20260716.json --summary build/effective_summary_20260716.json
```

然后对比：

```powershell
python tools/merged_snapshot.py compare --new-manifest docs/snapshots/pc-1.111.0.177-229314.json --old-view build/effective_view_20260716.json --old-root . --output build/20260716_to_229314_delta.json
```

分类为 `added_in_new_export`、`modified`、`unchanged` 和 `missing_from_new_export_unverified`。**后者不是「游戏删除了该表」**，只是新导出中缺失该类型文件。例如当前 ZIP 没有 `BinData/`，绝不能据此推断游戏删除了这些文件。

对比会根据 GitHub 仓库本身的七月配置重新计算**语义哈希**，而不是对比格式不同的两个原始 JSON 文件 SHA。输出的每表状态、字段增减、行数变化与记录 ID 集合哈希是否一致，均不包括具体游戏记录正文。它不会把旧层的 `RocoDataRows` 拼接进新版，也不会修改七月数据。

**注意：此版仅对比记录 ID 集合指纹是否一致，不会声称已精确计算逐 ID 新增、删除、修改清单。** 真正的逐记录内容差异必须同时能读取两个版本的 JSON 文件。原始数据不提交到公共 GitHub，后续如确认发布权限，再讨论单独维护数据快照的方案。

## 待解决的来源问题

1. 核对 107 个 Schema 字段不一致的表。FModel 在合并 Pak 后选择同名 `.non`，并不保证每一张表都与来源 Pak 层同版本；需要按表校准时再对单个问题表进行验证。
2. `BinData` 当前没有导出。7 月历史基准中有三份空记录文件，不因这次缺失自动认定已删除。
3. 若希望验证每张表实际生效归属，需在客户端确认 Pak 挂载优先级或提供按表来源日志。FModel 合并列表仅是候选有效视图。
4. 若发布包含原始游戏文本的数据文件，须先确认游戏数据再分发权限；此仓库现阶段只提交原创工具、可复现的哈希和分析结果。
