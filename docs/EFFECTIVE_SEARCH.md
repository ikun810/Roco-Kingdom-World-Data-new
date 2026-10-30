# 候选有效配置：跨表名称检索与增量差异（独立只读工具）

`tools/effective_search.py` 直接使用 `tools/effective_view.py` 生成的**单一候选有效视图**。每张表只选择一个 Pak 层的整份文件，**不把不同补丁层的 `RocoDataRows` 拼接或覆盖合并**，也不创建默认 SQLite 数据库。

## 1. 使用现有数据生成候选有效视图

在仓库根目录运行（Python 3.10+，仅标准库）：

```powershell
python tools/build_catalog.py --root . --snapshot 2026-07-16 --output build/catalog_20260716.json --summary build/catalog_summary_20260716.json --strict
python tools/effective_view.py build --catalog build/catalog_20260716.json --output build/effective_view_20260716.json --summary build/effective_summary_20260716.json
```

该优先级是依据 Pak 文件名的标准 Unreal 规则**推导出的候选结果**，并非游戏运行时已证实的自定义挂载顺序。所有查询结果均继承 `pak_mount_order_verified=false`。

## 2. 跨表名称搜索

默认搜索预选的安全名称字段，覆盖精灵、技能、地图、任务、物品、NPC 和赛季。默认**不会**搜索剧情对白、长描述、资源路径或动态脚本内容。

```powershell
# 搜索多个领域的名称，单次最多展示 20 条结果
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --query 喵喵

# 限定领域（允许重复 --domain）
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --query 幻梦 --domain season
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --query 月牙湖 --domain map --limit 10

# 指定表及名称字段
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --table SEASON_CONF --field s_title_subtitle --query 铅字幻梦 --exact
```

可选领域：`pet`、`skill`、`map`、`task`、`item`、`npc`、`season`。结果保留表名、ID、命中名称字段、源 Pak 层、总命中数与是否截断；不会把结果写回源文件，跨表不会返回下层已被整文件覆盖的旧行。输出 JSON 仅在本地命令终端显示；请勿将大量正文查询输出直接上传为公共 CI artifact。

## 3. 两个版本的增量差异

获取了新的客户端静态配置并生成新的 `effective_view` 后：

```powershell
python tools/effective_search.py compare --before build/effective_view_20260716.json --after D:\roco-next\build\effective_view_new.json --output build/effective_diff.json
```

该比较**不读取原始记录正文**，仅比较被选中表及本地化文件的 SHA-256。报告区分：新增、删除、变更、来源层迁移但内容相同、未变化，并提供变更表的行数增减。文件 SHA-256 不同仅说明该完整文件变化，**不等于**具体有哪些 ID 变化。

如需要精确 ID 增删改，且本地持有两套合法来源，可另加：

```powershell
python tools/effective_search.py compare --before build/effective_view_20260716.json --after D:\roco-next\build\effective_view_new.json --before-root . --after-root D:\roco-next --row-ids --sample-limit 10 --output build/effective_row_diff.json
```

此时只会加载**被选中且发生变化的配置表**，先复核所选文件的哈希，再按同一 ID 的规范化内容哈希比较，仅输出 ID 数量及少量样本，**不输出游戏正文**。新的版本必须先以独立来源快照保存；不要直接覆盖既有 Pak 文件。

## 4. 范围与限制

- 仅索引 **已经解码的 JSON 文件**。工具不会获取、解密或分析游戏运行中的私有资源。
- 同名配置采用整文件替换；没有高层文件时继承下层，未知挂载顺序不标记为已核实。
- `zh_CN` 和 `zh_Hans` 不是自动等价语言，快照差异分别保留。
- 在本地按需读取时逐文件校验 SHA-256；源文件改变而索引未更新会明确报错。
- 所有输出应写在未纳入版本控制的 `build/` 等独立位置；不会修改原始 Pak。
- **版本比较报告是数据源差异，不是游戏运行状态或正式赛季生效证明**。对外发布仍应遵循原始配置的版权与再分发边界。
