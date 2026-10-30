# PC `1.111.0.177 (229314)` 本地发行候选与发布门槛

本仓库有两种不同的内容，**不要混淆**：

1. `pakchunk4-*`：仓库现有的 2026-07-16 历史分层 JSON，保留原貌。
2. `docs/snapshots/pc-1.111.0.177-229314.json`：2026-10-30 从用户 FModel 合并导出 ZIP 生成的**元数据清单**；不是含有游戏配置正文的最新版数据库。

本工具 `tools/release_candidate.py` 将用户本地 `Bin(1).zip` 与 PR #6 元数据、PR #7 Schema 血缘报告逐个文件交叉校验。审核报告公开仓库内仅含哈希、字段名、记录数量及数据类型统计。输出完整数据的 `--package` 仅用于用户**本地检查**，未经权限审核不应提交到公开仓库。

## 1. 本地逐文件复核并生成审核报告

仅需要 Python 3.10+ 的标准库。用户自己合法取得的 FModel 导出保留在本地，无需上传至 GitHub Actions。

先生成 PR #7 Schema 血缘报告，或下载当时的 [GitHub Actions `roco-229314-schema-lineage` artifact](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41069687803/artifacts/12984811727)。当前 `main` 已有全部七月历史 Schema，故可重算：

```powershell
python tools/schema_lineage.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --history-root . --output build/schema_lineage_229314.json --summary build/schema_lineage_summary_229314.json
```

审核**原始 ZIP 的全部文件和表的语义哈希**：

```powershell
python tools/release_candidate.py --source 'D:\Data\Bin(1).zip' --manifest docs/snapshots/pc-1.111.0.177-229314.json --lineage build/schema_lineage_229314.json --report build/release_qa_229314.json
```

审核会检查：原始 ZIP SHA256；全部数据文件、Schema、本地化文件集合；所有普通表与 ROW 独立变体的 `RocoDataRows` 哈希、ID 集合、记录数量和字段；全部 Schema 语义哈希；本地化哈希；S1–S4 是否存在；PR #7 指出的 33 张新增字段表中各字段的出现次数和 JSON 类型。字段差异只标记，不删除任何数据。

`ROGUE_CHALLENGE_GLOBAL_CONFIG` 存在以参数名称为 map key、以数字 `id` 另行标识的记录模式。这会产生 ID 校验差异，但不自动构成损坏证据。

## 2. 可选：准备本地完整候选包

只在上述校验成功后运行：

```powershell
python tools/release_candidate.py --source 'D:\Data\Bin(1).zip' --manifest docs/snapshots/pc-1.111.0.177-229314.json --lineage build/schema_lineage_229314.json --report build/release_qa_229314.json --package build/Roco-World-PC-1.111.0.177-229314-local-review.zip
```

该 ZIP 只在本地生成，包含原始 2,314 份已经解码的 `Bin/` JSON、对应元数据和技术审核报告。其逻辑目录是**合并后的一个候选视图**，不是逐层 Pak 历史快照，也没有将 ROW 活动配置拼入国内普通表。

默认不发布完整 JSON 文件至公共 GitHub 仓库；原始 `.pak` 资源体积大且包含与配置无关的资源，**不属于本项目必要的新版数据库发布内容**。

## 3. CI 的核验范围

仓库中无需私有 ZIP 就可以复验报告的内在一致性：

```powershell
python tools/release_candidate.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --lineage build/schema_lineage_229314.json --report docs/reports/pc-1.111.0.177-release-qa.json --check-published-report
```

**重要区别**：CI 的 `--check-published-report` 仅检查已登记元数据与报告互相一致，**不能重读上传者本地的 ZIP**。实际 ZIP 全量字节核对只在本地 `--source` 模式完成；不可把 CI metadata pass 描述为 GitHub 已获取、复测或公开发布完整原始数据。

## 4. 正式发布条件

- [x] 原始 ZIP 全量文件哈希和记录语义哈希核对一致；已生成可重复生成的本地候选包
- [x] 七月历史数据未改变；ROW 独立处理；S4 赛季记录存在
- [x] 33 张涉及新增字段的表已做记录级**字段出现频率/数据类型**检查
- [ ] 将其中重要 `.bytes` 与新版同 Pak/同版本 `.non` 明确匹配，并核验解码准确性，特别是 `PETBASE_CONF`、`NPC_CONF`、`MODEL_CONF`、赛季活动表
- [ ] 确定版权、许可证及游戏服务条款是否允许**公开再分发游戏配置正文**；如不能，则继续只发布程序、技术报告与元数据，完整候选包仅用户本地保存
- [ ] 准备正式发布渠道、打版本 tag、验证下载安装/升级路径

**在上述未完成项关闭前，状态为 `candidate_unreleased`，不能将其称作已正式发布的完整版。**
