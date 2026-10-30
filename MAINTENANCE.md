# 《洛克王国：世界》数据仓库维护入口

主仓库：**https://github.com/ikun810/Roco-Kingdom-World-Data-new**  
数据来源：`candyflosssss/Roco-Kingdom-World-Data`  
基准：`93e9130bc7b53d370003571fa266d1487a2a43bf`（2026-07-16 仓库快照）  
维护面板：https://trello.com/b/HqUtG2Ey

## 已有数据

现有基础 Pak 和四个补丁 Pak 保持原来的独立目录。新工具**不重写、移动或覆盖**这些游戏数据。分层扫描、差异和 SQLite 都是可选维护能力，不是使用本仓库的前置条件。

## 快速开始（Python 3.10+，仅标准库）

在新仓库根目录执行：

```powershell
python -m unittest discover -s tests -v
python tools/pak_layers.py analyze --root . --output ../roco-maintenance-output/pak_inventory_20260716.json
```

第二条命令读取五层 Pak、输出 SHA-256、表名覆盖情况和 Schema 缺失统计，不自动合成 Pak。

如需研究某层的具体 JSON 和跨版本差异，再阅读 [`docs/DATA_MAINTENANCE.md`](docs/DATA_MAINTENANCE.md)。

## 直接查询（r0.4 新增）

不需要先合成 Pak 或导入 SQLite，直接在指定层的已解码 JSON 中查询：

```powershell
python tools/roco_lookup.py --root . layers
python tools/roco_lookup.py --root . tables --layer pakchunk4-WindowsNoEditor_2_P --filter SEASON
python tools/roco_lookup.py --root . get --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --id 3
python tools/roco_lookup.py --root . find --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --field s_title_subtitle --contains 幻梦
python tools/roco_lookup.py --root . trace --table SEASON_CONF --id 3
```

`trace` 展示各层同一 ID 的内容指纹，不判断哪一层实际生效；`find` 默认最多展示 20 条匹配，避免大量输出游戏对白。每次查询只读对应本地 JSON。

## 约定

- 原始 Pak 分层保留；不以文件名顺序推定游戏实际挂载顺序。
- 新的数据版本用单独来源标记，不覆盖历史快照。
- 当前仓库基准包含 S1–S3 赛季记录，不代表已包含最新游戏版本。
- 未明确授权的游戏配置、对白等资料不额外再分发；本次补丁只提供原创维护代码及元数据。
