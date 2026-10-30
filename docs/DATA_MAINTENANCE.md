# 2026-07-16 数据仓库维护操作手册

仓库：https://github.com/ikun810/Roco-Kingdom-World-Data-new  
GitHub 基准提交：`93e9130bc7b53d370003571fa266d1487a2a43bf`  
工具：`versioned_db.py` 0.2.0 + `pak_layers.py` 0.1.0 + `roco_lookup.py` 0.1.0  
维护面板：https://trello.com/b/HqUtG2Ey

## 1. 当前目录结构

```text
Roco-Kingdom-World-Data-new/
├── pakchunk4-WindowsNoEditor/
├── pakchunk4-WindowsNoEditor_0_P/
├── pakchunk4-WindowsNoEditor_1_P/
├── pakchunk4-WindowsNoEditor_2_P/
├── pakchunk4-WindowsNoEditor_3_P/
├── _summary.json
└── README.md
```

上述内容保持原貌。本补丁额外添加 `tools/`、`tests/`、`docs/`、`MAINTENANCE.md` 和 `.github/workflows/`，不替换仓库原 README 或任何 Pak 文件。

## 2. 首次使用：只查看分层目录，不合成数据

在新仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
python tools/pak_layers.py analyze --root . --output ../roco-maintenance-output/pak_inventory_20260716.json
```

结果会包含全部 `BinDataCompressed/*.json` 的 SHA-256、文件名重复层列表、每层 Schema 数量和每个本地化目录的 JSON 数。报告位于仓库之外的 `../roco-maintenance-output/`，原因是工具避免在原始数据树内写输出。

公开仓库检查所得参考：5 层压缩表数分别 675/564/119/480/26，跨层不同表文件名共 823，重复出现在至少两层的文件名有 582。实际扫描应按你克隆的仓库文件为准。`_summary.json` 来自原仓库的数据整理记录，不应替代工具实扫结果。

## 3. 无需合成：直接按 Pak 层查找资料

所有查询均为**离线只读**，不需要数据库构建、Pak 合成或任何额外依赖。在仓库根目录执行：

```powershell
python tools/roco_lookup.py --root . layers
python tools/roco_lookup.py --root . tables --layer pakchunk4-WindowsNoEditor_2_P --filter SEASON
python tools/roco_lookup.py --root . get --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --id 3
python tools/roco_lookup.py --root . find --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --field s_title_subtitle --contains 幻梦 --limit 10
python tools/roco_lookup.py --root . trace --table SEASON_CONF --id 3
```

`get` 输出一条原始 JSON 记录并附该层文件的 SHA-256；`find` 只展示匹配字段摘要，最多 100 条；`trace` 逐层显示相同 ID 是否存在及内容哈希是否相同，不据此推定补丁优先级。真实查询结果以当前 clone 的文件为准。

## 4. 可选：构建 Pak 合成候选

只有需要同名表的统一检索视图时才做，不是 Fork 或日常维护的前置条件。以下补丁顺序只是演示参数语法，**尚未核验为游戏正式的实际挂载优先级**：

```powershell
python tools/pak_layers.py stage --root . --order pakchunk4-WindowsNoEditor pakchunk4-WindowsNoEditor_0_P pakchunk4-WindowsNoEditor_1_P pakchunk4-WindowsNoEditor_2_P pakchunk4-WindowsNoEditor_3_P --out-dir ../roco-maintenance-output/july2026-candidate
```

`stage` 不修改 Pak 原始文件，输出 `staging_manifest.json`，逐表记录 `data_layer`、`schema_layer`、哈希、候选顺序及 `order_verified=false`。Schema 可跨层借用，但不会将借用证明为兼容；若需要真实客户端生效数据，另行核实挂载顺序与 Schema 关系。

## 5. 可选：将候选导入离线 SQLite

```powershell
python tools/versioned_db.py inventory --data-dir ../roco-maintenance-output/july2026-candidate/BinDataCompressed --schema-dir ../roco-maintenance-output/july2026-candidate/BinConf --output ../roco-maintenance-output/inventory.json
python tools/versioned_db.py ingest --data-dir ../roco-maintenance-output/july2026-candidate/BinDataCompressed --schema-dir ../roco-maintenance-output/july2026-candidate/BinConf --database ../roco-maintenance-output/roco_versions.sqlite --snapshot-id july2026-pak-order-unverified --source-kind third_party_historical --source-ref https://github.com/ikun810/Roco-Kingdom-World-Data-new --source-commit 93e9130bc7b53d370003571fa266d1487a2a43bf --source-date 2026-07-16 --output ../roco-maintenance-output/ingest.json
python tools/versioned_db.py verify --data-dir ../roco-maintenance-output/july2026-candidate/BinDataCompressed --schema-dir ../roco-maintenance-output/july2026-candidate/BinConf --database ../roco-maintenance-output/roco_versions.sqlite --snapshot-id july2026-pak-order-unverified --output ../roco-maintenance-output/verify.json
```

`ingest` 不修改数据源；同一快照不可用不同文件覆盖。`manifest` 和 `compare` 用于查看版本与字段差异。数据库保留实际配置内容，因此默认只保存在本地，不自动发布。

**未包含**：直接下载客户端、解密工具、BinLocalize/BinData 全量入库、实际 Pak 挂载顺序确认、游戏实时版本认证。

## 6. 新版持续更新

来源登记在 `docs/SOURCE_REGISTER.json`：分别填写仓库提交日期、来源声明快照日期和有证据的真实游戏 Build。每次新来源先保存可重现哈希和合法来源，再另建快照；不修改 2026-07-16 原始数据。CI 只运行原创工具的合成测试。

关于授权：第三方仓库可读不自动等于游戏数据有额外再分发许可。维护脚本、测试和原创分析可单独审查发布，未经授权的原始配置/对白不应另外打包传播。
