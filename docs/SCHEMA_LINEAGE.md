# 1.111.0.177：FModel 合并导出的 Schema 血缘诊断

本工具针对已合并的 [`pc-1.111.0.177-229314.json`](snapshots/pc-1.111.0.177-229314.json) 元数据，检查其中 **107 份 `fields_not_in_schema` 警告**。此类警告严格表示：**解码记录中出现了所附同名 Schema 没有声明的字段**，不等于 Schema 声明的所有字段都必须出现在每条记录中。

本仓库的 2026-07-16 历史 `BinConf/*.json` 有多个 Pak 补丁层，工具读取其中已声明的顶级字段和规范化 Schema 哈希，帮助区分：

- **同名 Schema 指纹匹配**：新导出里附的 Schema 与七月某个历史 Pak 层的 Schema 是否完全相同（仅指规范化 JSON 值一致）。
- **字段在历史补丁中出现过**：即使新导出的同名 Schema 不声明某个字段，它是否存在于七月的其它层 Schema 中。
- **历史字段覆盖程度**：是否至少有一份历史 Schema 声明了当前该表所有观察到的字段，或者仅声明了所有“多余字段”。
- **截至七月没有出现过的字段**：保留为新版新增字段或无法解释的结构差异候选，不因无历史匹配就宣布解析失败。

**这些诊断不能证明哪份 Schema 与最新版 `.bytes` 的二进制布局真正兼容。** 要确定源头需取得该 `.bytes` 对应 Pak 层的 `.non`，核对字段类型、偏移、长度、嵌套结构，而不仅仅比字段名称。我们不会自动拿七月的旧 Schema 去重解新版文件。

## 运行

在仓库根目录执行（Python 3.10+，标准库）：

```powershell
python tools/schema_lineage.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --history-root . --output build/schema_lineage_229314.json --summary build/schema_lineage_summary_229314.json
```

也可以先运行合成测试：

```powershell
python -m unittest discover -s tests -p test_schema_lineage.py -v
```

`build/` 受 `.gitignore` 排除。输出只含源表名、字段名、文件路径、哈希比较和统计，不复制游戏记录或对白。`schema_lineage_229314.json` 为逐表血缘细节，`schema_lineage_summary_229314.json` 为紧凑汇总。

GitHub Actions 的 `Audit October 2026 merged-export schema lineage` 工作流运行真实仓库检查，并把上述两份结果作为 30 天保留的 Artifact 上传。Windows 和 Ubuntu 都会在 `Offline data maintenance tests` 工作流中运行合成测试。

## 调查规则

1. `exported_schema_same_as_base`：导出的 Schema 指纹与七月**基础层**相同的异常表数。指纹相同并不能自动证明 FModel 实际选择了哪个 Pak 来源文件。
2. `historical_full_extra_coverage`：至少一份七月历史 Schema 覆盖该异常表**所有**超出导出 Schema 声明的字段。可能是 Schema 版本错配的线索，并非解码已验证。
3. `historical_full_observed_coverage`：至少一份旧 Schema 覆盖该表**全部观察到**的字段。仍然需要二进制类型与行偏移检验。
4. `never_seen_field_occurrences`：在此前五层 Schema 中均未找到的多余字段发生次数。不要自行填补或重新命名。
5. `ROW` 国际服表单独计数，不能据此判断国内正常配置有错误。

## 实例与下一步

前置实查发现：七月 `_2_P` Schema 已包含 `SEASON_CONF` 的 5 个异常字段和 `ACTIVITY_CONF` 的 5 个异常字段；`PETBASE_CONF` 的 9 个异常字段中有 7 个已出现在七月 `_2_P`。这证明至少部分警告并非首次发现的新字段。完整统计以工作流产物为准。

优先根据诊断结果检查 `SEASON_CONF`、`PETBASE_CONF`、`ACTIVITY_CONF`、`NPC_CONF`、`WORLD_MAP_CONF`。必要时由用户从 FModel 对这些**少量**关键表另行导出来源 Pak 的 `.non`/`.bytes`，无需重新上传整个游戏客户端或 381 个 Pak。未经游戏数据再分发许可，不将完整游戏原文提交到公开仓库。

## 已完成的实际扫描结果

2026-10-30 GitHub Actions [运行 41069687803](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41069687803) 已成功扫描 1,315 份历史 Schema，并检查 107 张异常表。**97 张异常表的导出 Schema 与七月基础层完全相同；73 张至少有一份历史 Schema 包含全部已观察字段；33 张出现七月历史从未声明过的字段**。完整统计、重点表和待核对清单见 [实跑报告](reports/pc-1.111.0.177-schema-lineage.md)。
