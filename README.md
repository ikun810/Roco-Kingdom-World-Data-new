# 洛克王国：世界 数据仓库

已解码配置在 `data/current.zip`；历史数据保留在 `pakchunk*` 目录。

## 使用（Python 3.10+）

```powershell
git clone https://github.com/ikun810/Roco-Kingdom-World-Data-new.git
cd Roco-Kingdom-World-Data-new
python tools/query.py tables --filter SEASON
python tools/query.py get --table SEASON_CONF --id 4
python tools/query.py search --domain pet --query 喵喵
```

需要全部 JSON 时，可执行：

```powershell
python -m zipfile -e data/current.zip build/current
```

`MESSAGE_CONF`、`TASK_CONF`、`REWARD_CONF`、`SELECT_CONF` 的 Schema／文字绑定错误已从原始二进制复现。使用四表修复和本轮引用资料时，运行：

```powershell
python tools/raw_content.py verify
python tools/raw_content.py export --output-dir build/raw-content
```

来源、整表视图及 659 条引用资料的用法见 [原始配置重解码](docs/RAW_CONTENT.md)。原始 `current.zip` 保留作为固定基线；旧的历史补缺路径见 [补充资料用法](docs/CONTENT_SUPPLEMENT.md)。

数据为客户端静态配置的第三方导出，非官方服务；使用与再分发应遵守权利人的许可和相关规定。
