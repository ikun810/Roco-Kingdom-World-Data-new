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

数据为客户端静态配置的第三方导出，非官方服务；使用与再分发应遵守权利人的许可和相关规定。
