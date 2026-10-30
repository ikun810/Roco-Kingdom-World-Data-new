# 洛克王国：世界 · 结构化数据仓库

本仓库保存《洛克王国：世界》客户端静态配置的**已提取、已解码 JSON**、协议资料与只读分析工具，供本地检索、版本比较和资料研究使用。它**不是**游戏源码、在线游戏数据库，也**不提供**直接从 `.pak` 一键解包到 JSON 的完整程序。

> **现有数据快照：2026-07-16（仓库资料日期，不是当前客户端版本）**。数据来源为 [`candyflosssss/Roco-Kingdom-World-Data`](https://github.com/candyflosssss/Roco-Kingdom-World-Data)，起始提交 `93e9130bc7b53d370003571fa266d1487a2a43bf`。本仓库还包含后续独立开发的查询、目录扫描和差异工具。**S4 及其后续内容不能仅凭这份快照认定已收录。**

## 目录与工具一览

```text
Roco-Kingdom-World-Data-new/
├── pakchunk4-WindowsNoEditor/         # 基础层：已解码配置
├── pakchunk4-WindowsNoEditor_0_P/     # 补丁层：已解码配置
├── pakchunk4-WindowsNoEditor_1_P/
├── pakchunk4-WindowsNoEditor_2_P/
├── pakchunk4-WindowsNoEditor_3_P/
├── tools/
│   ├── roco_lookup.py                # 指定 Pak 层查询、逐层追踪
│   ├── build_catalog.py              # 全层表/字段/哈希索引
│   ├── effective_view.py             # 单一候选有效视图
│   ├── effective_search.py           # 跨表名称检索及版本差异
│   ├── pak_layers.py                 # 分层文件扫描
│   └── versioned_db.py               # 可选本地 SQLite 快照
├── docs/                              # 进阶说明与来源登记
├── tests/                             # 不依赖游戏客户端的单元测试
└── build/                             # 运行时本地生成；Git 已忽略
```

每个 `pakchunk.../` 文件夹模拟一层客户端资源归档中的逻辑目录，常见内容有 `Bin/BinDataCompressed/*.json`、`Bin/BinConf/*.json`、`Bin/BinLocalize/`、`PB/` 和 `_logs/`。这些是**解码结果文件夹，不是原始 `.pak` 归档**。其中 `RocoDataRows` 为配置记录表，`BinConf` 为对应的结构描述。

同路径的高优先级补丁文件应**整文件替换**低层文件，而不是将不同层的 `RocoDataRows` 按 ID 拼在一起。脚本默认按标准 Unreal 文件名顺序建立**候选**视图；本游戏是否采用自定义 Pak 挂载顺序尚未核验，报告始终标注 `pak_mount_order_verified=false`。详情见 [有效视图说明](docs/EFFECTIVE_VIEW.md)。

## 1. 直接使用仓库现有数据（无需解包）

需要 Windows/macOS/Linux 上的 **Python 3.10 或更新版本**。已有工具只依赖 Python 标准库，不必额外安装数据库服务。

```powershell
git clone https://github.com/ikun810/Roco-Kingdom-World-Data-new.git
cd Roco-Kingdom-World-Data-new
python --version
python -m unittest discover -s tests -v
```

### A. 按 Pak 层直接查询

```powershell
# 查看已有层与配置表
python tools/roco_lookup.py --root . layers
python tools/roco_lookup.py --root . tables --layer pakchunk4-WindowsNoEditor_2_P --filter SEASON

# 在指定层读取记录、按字段搜索、追踪同一 ID 在不同层的内容变化
python tools/roco_lookup.py --root . get --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --id 3
python tools/roco_lookup.py --root . find --layer pakchunk4-WindowsNoEditor_2_P --table SEASON_CONF --field s_title_subtitle --contains 幻梦
python tools/roco_lookup.py --root . trace --table SEASON_CONF --id 3
```

### B. 建立单一候选有效视图并跨表搜索（推荐）

在**仓库根目录**运行，产物只写入 `build/`，不修改原始数据：

```powershell
python tools/build_catalog.py --root . --snapshot 2026-07-16 --output build/catalog_20260716.json --summary build/catalog_summary_20260716.json --strict
python tools/effective_view.py build --catalog build/catalog_20260716.json --output build/effective_view_20260716.json --summary build/effective_summary_20260716.json

# 按 ID 查询最终选中的 SEASON_CONF
python tools/effective_view.py get --root . --view build/effective_view_20260716.json --table SEASON_CONF --id 3

# 在有效配置里跨表搜索名称（不会扫描对白全文）
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --query 铅字幻梦 --domain season
python tools/effective_search.py search --root . --view build/effective_view_20260716.json --query 喵喵 --domain pet --limit 10
```

跨表搜索支持 `pet`、`skill`、`map`、`task`、`item`、`npc`、`season`。要比较两个版本，先分别生成各自的 `effective_view`，然后：

```powershell
python tools/effective_search.py compare --before build/effective_view_20260716.json --after build/effective_view_new.json --output build/effective_diff.json
```

此命令只比较**索引/文件哈希**，不需要复制整个 SQLite。若确有需要，可参阅 [跨版本 ID 差异](docs/EFFECTIVE_SEARCH.md) 和 [本地 SQLite 快照](docs/DATA_MAINTENANCE.md)。新增快照应有独立目录和真实来源登记，不要直接覆盖七月数据。

## 2. 从本地游戏客户端提取 Pak 配置（Windows）

> **这是独立于上述 Python 工具的前置提取流程**：`.pak` / `.utoc` / `.ucas` → FModel 导出原始配置 → 使用相应解码器转换 `.bytes` / `.non` → 得到本仓库能查询的 JSON。**FModel 导出原始文件不等于已经完成自定义 Bin 格式解码。**

### 2.1 准备工具与定位资源包

1. 从 [FModel 官方仓库](https://github.com/4sval/FModel) 或其 [安装说明](https://github.com/4sval/FModel/wiki/Installing-FModel) 获取 Windows 版 FModel，按提示安装它需要的运行库。软件操作可参考 [官方 Getting Started](https://github.com/4sval/FModel/wiki/Getting-Started)。
2. 在你**合法持有且有权分析**的 PC 客户端安装目录中查找 `Content/Paks`（具体目录随安装方式变化）；确认存在 `.pak`，或成对出现的 `.utoc` + `.ucas`。**请勿改动安装目录中的文件。**
3. 可选：在 PowerShell 中记录包文件清单，便于定位哪个补丁层变化（下面会提示你输入实际路径，无需预先填写假的游戏路径）：

```powershell
$archiveDir = Read-Host '输入游戏 Content\Paks 的完整路径'
New-Item -ItemType Directory -Force -Path build | Out-Null
Get-ChildItem -LiteralPath $archiveDir -Recurse -File |
  Where-Object { $_.Extension -in '.pak', '.utoc', '.ucas' } |
  Select-Object FullName, Length, LastWriteTime |
  Export-Csv -LiteralPath 'build/client_archives.csv' -NoTypeInformation -Encoding UTF8
```

这份 CSV 可能包含你的本机用户名、安装路径，只用于本地研究，不要原样公开提交。

### 2.2 在 FModel 中浏览、导出原始文件

1. 打开 FModel，选择 **Directory → Selector**。在 **Add Undetected Game** 中建立本地游戏条目，目录选择上述实际 `Content/Paks` 文件夹，设置与客户端匹配的 Unreal Engine 版本（**本仓库未核实当前客户端的具体引擎小版本，不要照抄其他游戏的版本**）。
2. 在 **Archives** 页面查看可读的 `.pak` / `.utoc` 列表。**要保留每层来源，建议一次只选择一个基础包或补丁包进行提取**，不要直接使用 `All` 后把覆盖后的文件误当成某一层的独立原始内容。不同 FModel 版本的菜单名称可能略有差异。
3. 在 **Folders / Packages** 页面查找 `NRC/Content/ScriptC/Data`。这是仓库来源快照的配置逻辑路径，**不保证所有新版客户端都完全一致**。重点关注：
   - `Bin/BinConf`：Schema 结构（原始导出可能是 `.non`）；
   - `Bin/BinDataCompressed`、`Bin/BinData`：配置数据（原始导出可能是 `.bytes`）；
   - `Bin/BinLocalize`：语言相关原始配置；
   - `Config`、`PB`：按研究目标选取。
4. 在文件上右键选择 **Export Raw Data**，或在对应目录上使用 **Export Folder's Packages Raw Data**（具体文字随版本变化）。将**原始**字节文件导出到 FModel 的输出目录。不要以“Save Properties 为 JSON”代替 `.bytes` 原始文件导出。
5. 将不同 Pak 的**导出副本**分别保存在以原始 Pak 名称命名的目录中，记录来源客户端版本、归档文件名与导出日期。不要混合、覆盖不同层，也不要将导出物直接写回游戏安装目录。

整理后的本地原始数据通常可按以下形式保存（这是**组织示例**，不是本仓库已经包含的文件）：

```text
extracted/<本次快照日期>/
├── pakchunk4-WindowsNoEditor/
│   └── Bin/
│       ├── BinConf/              # 从归档导出的 .non 等原始结构文件
│       └── BinDataCompressed/    # 从归档导出的 .bytes
├── pakchunk4-WindowsNoEditor_0_P/
│   └── Bin/...
└── ...                          # 其余实际存在的补丁层
```

### 2.3 将原始配置变为可查询的 JSON

**当前主仓库的 `tools/build_catalog.py`、`effective_view.py`、`effective_search.py` 都只处理已解码 JSON，它们不负责 `.pak` 解包，也不能直接将 `.bytes` 或二进制 `.non` 转换为 JSON。**

历史资料仓库提供了 [`Bin/decode_bin.py` 示例解码器](https://github.com/giraffe995/Roco-Kingdom-World-Data/blob/main/Bin/decode_bin.py)，可作为研究参考，但不属于本仓库工具链的已验证新版导入功能。**该脚本实际通过 `json.load` 读取 Schema，因此需要已经转换成 JSON 的结构定义；不能把任意二进制 `.non` 直接传给它并假定成功。** 新版配置如果缺少可用 Schema、格式发生变化，须先解决解码兼容性，再导入。

要接入本仓库，转换后的每张配置表至少应符合如下结构，`BinConf/*.json` 应提供与实际表匹配的字段定义：

```json
{
  "RocoDataRows": {
    "123": { "id": 123, "name": "示例记录" }
  },
  "LocalizationStrings": {}
}
```

上方只是**说明 JSON 格式的示例**，不是实际游戏配置。对同名配置采用整文件覆盖，不能把不同 Pak 里较低层的记录拼入较高层。应保留原始归档来源、文件 SHA-256、解码器版本、Schema 来源及失败日志，确认来源及许可后再进入新的数据快照。使用 `docs/SOURCE_REGISTER.json` 登记版本与出处。

### 2.4 常见问题

| 现象 | 检查方向 |
| --- | --- |
| FModel 中没有显示归档 | 检查选择的是实际 `Content/Paks`；`.utoc` 是否有配套 `.ucas`；游戏路径/引擎版本是否匹配 |
| 归档显示加密、拒绝读取 | 仅使用经授权提供的解密信息；不要绕过访问控制，也不要将密钥提交到仓库 |
| 能导出 `.bytes` 但 Python 报不是 JSON | 正常；FModel 仅完成原始提取，还需要适配该版本的自定义 Bin 解码器 |
| 只有 `.non`，解码器报告 Schema 无法解析 | 二进制 Schema 与 JSON Schema 是不同阶段，需要先把结构转换成解码器可读的 JSON |
| 某一补丁层缺少表/Schema | 可能继承自更低层，参考 `_logs/schema_usage.csv`；不能凭最新 Schema 名称推断兼容性 |
| 搜索结果和运行中的游戏不一致 | 核对仓库快照日期、Pak 覆盖假设和客户端版本；本仓库不是实时数据接口 |

## 3. 升级与维护约定

- **只读维护**：不修改游戏客户端、不在运行中的游戏进程注入、不访问私有服务器接口、不绕过加密或反作弊保护。
- **按快照管理**：当前仓库的 2026-07-16 是历史基准，新客户端资料必须单独保存来源快照与文件哈希，验证后再比较；不将“仓库提交日期”当成“游戏配置生效日期”。
- **按文件覆盖**：补丁的同逻辑路径文件整体替换，缺失文件从低层继承；运行时是否使用该挂载优先级仍需实证。
- **谨慎发布**：公开源仓库可读取，不代表原始游戏数据、对白和客户端资源获得再分发许可。默认只发布原创工具及允许发布的技术元数据，未经确认的原始提取物保存在本地。

进一步使用说明：[目录索引](docs/CATALOG.md) · [有效视图](docs/EFFECTIVE_VIEW.md) · [名称检索和版本比较](docs/EFFECTIVE_SEARCH.md) · [数据维护与可选 SQLite](docs/DATA_MAINTENANCE.md)。
## 2026-10-30 PC 客户端候选快照（元数据）

新增 PC `1.111.0.177 (229314)` FModel 合并导出**元数据清单**及解析工具：[`docs/MERGED_SNAPSHOT.md`](docs/MERGED_SNAPSHOT.md)、[`docs/snapshots/pc-1.111.0.177-229314.json`](docs/snapshots/pc-1.111.0.177-229314.json)。该合并导出含 870 张普通表、675,341 条记录、870 份 Schema、571 份本地化以及 3 份 ROW 变体；107 张表存在字段与同名 Schema 不完全一致的警告，尚待验证。

**注意**：仓库原始五层 Pak 资料仍是七月历史基准；此 PR 只更新新版本的来源登记、哈希元数据、审计工具及比对报告，**没有上传新版游戏记录正文，也没有替换七月数据**。获得版权/来源许可确认前不将导出 JSON 直接发布；新版按表 Pak 来源仍待独立核实。参见 [来源登记](docs/SOURCE_REGISTER.json)。
