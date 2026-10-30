# 2026-07-16 数据索引实跑基准

本报告由仓库中 `tools/build_catalog.py` 扫描**实际五层 JSON 数据**生成，来自 2026-10-30 的 GitHub Actions 运行：

- [Build July 2026 data catalog · Run 41035220281](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41035220281)
- [索引产物 roco-20260716-catalog](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41035220281/artifacts/12967901848)（GitHub Actions 的产物有保留期限，不能替代永久版本归档）
- 源仓库基准提交：`93e9130bc7b53d370003571fa266d1487a2a43bf`
- 构建工具 PR：#2，变更仅涉及原创工具、文档和派生元数据。

## 实跑结果

| 指标 | 数值 |
| --- | ---: |
| Pak 层数 | 5 |
| 压缩 JSON 配置文件（跨层计次） | 1,864 |
| 非压缩 JSON 配置文件（跨层计次） | 3 |
| 数据 JSON 文件总数 | 1,867 |
| Schema JSON 文件总数 | 1,315 |
| 本地化 JSON 文件总数 | 772 |
| 不同名称的压缩配置表 | 823 |
| 含 BinData 在内的不同类型/表组合 | 826 |
| 出现在多个层的表类型 | 582 |
| 多层同名且内容 SHA256 不同的表类型 | 483 |
| 各层记录数相加（**不去重**） | 2,229,129 |
| 零记录的表文件 | 57 |
| 解析/数据封装错误 | 0 |

### 各层数据文件数

| 层 | BinDataCompressed | BinData |
| --- | ---: | ---: |
| `pakchunk4-WindowsNoEditor` | 675 | 3 |
| `pakchunk4-WindowsNoEditor_0_P` | 564 | 0 |
| `pakchunk4-WindowsNoEditor_1_P` | 119 | 0 |
| `pakchunk4-WindowsNoEditor_2_P` | 480 | 0 |
| `pakchunk4-WindowsNoEditor_3_P` | 26 | 0 |

## 统计解释

- `total_rows_across_layers` 含多个版本/补丁层对同一配置的重复计数；**不得**把 2,229,129 当作精灵数量、独立实体数量或游戏当前已生效的数据条数。
- 483 个不同内容哈希的同名表代表跨层变更候选；**不**能推定某个层优先覆盖另一层。
- `issue_count=0` 仅表示被扫描配置的 JSON 格式与记录容器满足工具检查，不代表字段语义、外键、版本号、客户端实际使用状态均已验证。
- 工具不读取客户端运行状态；本基准日期是**来源仓库声明快照日期**，不是对当前在线客户端构建号的证实。
- 产物只含技术元数据。未按某个特定版权许可重新发布原始游戏数据或完整对白。

## 下一阶段

1. 根据本报告对精灵、技能、任务、地图、对话等核心表建立按层数据索引和关联候选表。
2. 给跨层配置建立显式 `source_layer`、`schema_source_layer` 与 SHA256 溯源，待挂载规则证实时再生成有效视图。
3. 取得新版本后新建独立快照，与 2026-07-16 原始文件基线逐表比较。