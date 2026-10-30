# 全量配置目录与字段索引（2026-07-16）

此工具扫描已有的五层 Pak 解码目录，不下载客户端、不解析原始 Pak 包、不建立未经核实的生效覆盖顺序。仅生成文件元数据和 Schema 字段名，**不输出具体任务、精灵、对白等原始记录值**。

## 生成索引

```powershell
python tools/build_catalog.py --root . --snapshot 2026-07-16 --source-commit 93e9130bc7b53d370003571fa266d1487a2a43bf --output build/catalog_20260716.json --summary build/catalog_summary_20260716.json --strict
```

`build/` 目录已被 `.gitignore` 排除，避免将来源数据库的衍生大文件意外提交。GitHub Actions 的 **Build July 2026 data catalog** 工作流会在 PR 中对**实际仓库**执行索引并上传两份元数据报告；CI 报告的真实数量比 README 所列静态统计更准确。

`catalog_20260716.json` 包含每层每张表（BinDataCompressed 和 BinData）的相对路径、SHA256、文件字节数、记录数、观察到的顶级字段名称、同层 Schema 是否存在、跨层可能 Schema 的出处和 SHA256。本地化目录只列出各语言 JSON 文件的路径、字节数和 SHA256，不列出翻译文本。

`catalog_summary_20260716.json` 是紧凑统计和问题报告。表名重复、不同内容哈希的记录会单独计数；多份重复文件仍分别计入 `total_rows_across_layers`，**这不是游戏中独立实体的去重总量**。

## 状态和边界

- `pak_mount_order_verified=false`：不会根据层名称推定客户端实际加载优先级。
- `game_build_verified=false`：本工具仅记录仓库标注的 2026-07-16 快照日期。
- `schema_in_same_layer=false`：表示当前层没有同名 Schema；其他层的候选 Schema 不代表经过兼容性验证。
- `--strict`：遇到无效 JSON、数据表结构异常等会失败，留下问题报告便于修复。
- 所有源文件都只读。输出仅有原创分析和技术元数据。原始内容的授权及版本仍须独立管理。

此阶段完成后，按领域提供可查询的视图与索引，但不会自动修改、合并、删除任何源数据。
