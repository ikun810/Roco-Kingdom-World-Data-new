# PC 1.111.0.177 (229314) Schema 血缘实跑报告

来源：2026-10-30 用户提供的 FModel 合并导出，原始 ZIP 的 SHA-256 已在 [快照元数据](../snapshots/pc-1.111.0.177-229314.json) 内记录。本报告仅使用已提交的 **字段名、规范化 Schema SHA-256** 与仓库七月历史 `BinConf` 元数据，不包含游戏配置正文。

证据：GitHub Actions [Audit October 2026 merged-export schema lineage · 41069687803](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41069687803)，真实仓库测试完成并成功上传 [逐表诊断 artifact](https://github.com/ikun810/Roco-Kingdom-World-Data-new/actions/runs/41069687803/artifacts/12984811727)。

## 实测汇总

| 项目 | 实测 |
| --- | ---: |
| 历史 JSON Schema 数 | 1,315 |
| 新版导出所对照的表 / ROW 配置数 | 873（普通表 870 + ROW 3） |
| Schema 与七月某层完全相同 | 826 |
| 其中与七月基础层完全相同 | 678 |
| 其中仅与七月补丁层相同 | 148 |
| 暂未匹配历史 Schema 的条目 | 47 |
| 有观察字段超出导出 Schema 声明的表 | **107**（普通表 106 + ROW 1） |
| 这 107 张表中与七月基础层 Schema 相同 | **97** |
| 这 107 张表中至少有一份历史 Schema 覆盖全部多余字段 | **74** |
| 至少一份历史 Schema 覆盖全部观察字段 | **73** |
| 包含七月历史中未出现过字段的表 | **33** |
| 七月历史中未出现过的字段发生次数 | **56** |

**含义**：本次输出表的 Schema 多数仍能在七月五层历史中找到完全一致的版本。特别是 107 张异常表的导出 Schema **全部**匹配某个七月历史 Schema，其中 97 张匹配七月基础层。结合 FModel 在所有 Pak 中按名称检索 `.non` 的实现，**这支持导出的 Schema 与部分解码数据来自不同补丁时期的推断**，但不能直接证明其真实来源路径，也不能证明是客户端自身加载错误。新版本的记录已成功解码，不应据此将整套数据认定为损坏。

## 五张重点表

| 表 | 本次多余字段 | 导出 Schema 等于七月基础层 | 七月历史补丁的覆盖情况 | 仍未见于七月的字段 |
| --- | ---: | --- | --- | --- |
| `SEASON_CONF` | 5 | 是 | `pakchunk4-WindowsNoEditor_2_P` 覆盖 24/24 个观察字段 | 无 |
| `PETBASE_CONF` | 9 | 是 | `pakchunk4-WindowsNoEditor_2_P` 覆盖 132/134 个观察字段 | `habit_ai_group_info_id`、`head_marker_offset` |
| `ACTIVITY_CONF` | 5 | 是 | `pakchunk4-WindowsNoEditor_2_P` 覆盖 36/36 个观察字段 | 无 |
| `NPC_CONF` | 5 | 是 | `pakchunk4-WindowsNoEditor_2_P` 覆盖 78/79 个观察字段 | `can_be_bound_and_hidden` |
| `WORLD_MAP_CONF` | 4 | 是 | `pakchunk4-WindowsNoEditor_2_P` 覆盖 63/63 个观察字段 | 无 |

`SEASON_CONF` 四个赛季含 S4，但对应导出的 Schema 指纹仍等于七月基础层，七月 `_2_P` Schema 已能覆盖其全部 24 个观察字段。`PETBASE_CONF` 的 `habit_ai_group_info_id` 和 `head_marker_offset`、`NPC_CONF` 的 `can_be_bound_and_hidden` 则属于此前未在七月 Schema 中找到的字段，需要同版本 Schema 样本进一步确认。**七月旧 Schema 只是调查参照，不能直接替代新版 `.non` 去解包。**

## 优先需要核对的 33 张表

以下表的导出记录包含七月历史 `BinConf` 未声明过的字段。再次强调，此处只说明 **七月旧 Schema 无法解释该字段**，不是断言字段错误，也不需要因这些差异重新提取全部游戏 Pak。

- `BinDataCompressed/ACTIVITY_DROP_METHOD_CONF`：`day_got_limit_type`、`week_day_time`
- `BinDataCompressed/ACTIVITY_PET_CERTIFICATION`：`fullstar`
- `BinDataCompressed/ACTIVITY_RECALLBP_CONF`：`up_bp_name`
- `BinDataCompressed/ACTIVITY_SEASON_SPRINT_CONF`：`chasing_reward_title`、`exp_chasing_limit`、`instruction_desc`、`pass_exp_module_desc`、`pass_exp_progress_desc`、`season_bg_umg_path`、`task_group`、`window_title`
- `BinDataCompressed/ALL_RIDE_PET`：`monitor_data_version`
- `BinDataCompressed/AREA_FUNC_CONF`：`ascription_proprity`
- `BinDataCompressed/BALL_CONF`：`param_move`、`param_surface`
- `BinDataCompressed/BATTLE_CONF`：`is_pvp_season_music`
- `BinDataCompressed/BATTLE_PASS_CONF`：`bp_pass_select`
- `BinDataCompressed/BUTTON_SETTING_CONF`：`sort_id`
- `BinDataCompressed/CHAT_BUBBLE_CONF`：`item_quality`
- `BinDataCompressed/FURNITURE_ITEM_CONF`：`furniture_center_offset`
- `BinDataCompressed/LEVEL_SKILL_CONF`：`extra_machine_skill_group_id`
- `BinDataCompressed/MODEL_CONF`：`resource_inpackage_version`
- `BinDataCompressed/NORMAL_SHOP_CONF`：`resource_inpackage`
- `BinDataCompressed/NPC_CONF`：`can_be_bound_and_hidden`
- `BinDataCompressed/NPC_REFRESH_CONTENT_CONF`：`first_emerge_skill`
- `BinDataCompressed/PETBASE_CONF`：`habit_ai_group_info_id`、`head_marker_offset`
- `BinDataCompressed/PET_INFORMATION_CONF`：`condition_param2`
- `BinDataCompressed/PET_TOPIC_TYPE_CONF`：`is_show_in_magic_challenge`
- `BinDataCompressed/PLANT_GROW_CONF`：`plant_show_bagitem`
- `BinDataCompressed/PVP_CONF`：`end_time`、`rule_list`、`rule_num`、`rule_tips`、`start_time`
- `BinDataCompressed/PVP_RANK_CONF`：`share_bg`
- `BinDataCompressed/RELATIONTREE_ANIM_CONF`：`allow_broadcast`、`roleplay_id`、`simple_action_id`、`single_key`、`socialshare_type`
- `BinDataCompressed/RIDE_SOCKET`：`skill_socket_pc1`、`skill_socket_pc2`
- `BinDataCompressed/ROLEPLAY_BEHAVIOR_CONF`：`relationtree_anim_id`
- `BinDataCompressed/ROLEPLAY_PROP_CONF`：`related_function_id`
- `BinDataCompressed/SCENE_STATUS_WPST_CONF`：`is_afk_wandhold`
- `BinDataCompressed/SEASON_ADVENTURE_BADGE_LEVEL`：`badge_level_reward`、`badge_level_up`、`star_icon`
- `BinDataCompressed/SEASON_HANDBOOK_CONF`：`shining_collect_task`
- `BinDataCompressed/TREASURE_ITEM_CONF`：`if_last_safety_net`
- `BinDataCompressed/WEEKLY_CHALLENGE_EVENT_CONF`：`extra_reward_limit`、`extra_star`、`reward`
- `BinDataCompressed/WISH_EXCHANGE_CONF`：`wish_exchange`

## 后续处理

1. 在现有来源 ZIP 中继续保存 870 张有效候选配置；不要把 107 张都判为解析失败，也不要直接把七月 Schema 补丁覆盖为十月官方 Schema。
2. 优先根据 FModel 实际所选的 Pak，核对 `PETBASE_CONF`、`NPC_CONF`、`SCENE_RES_CONF` 等涉及新字段的 `BinConf/*.non`。需要时只提取这些少量 Schema 与对应 `.bytes`，按文件长度和表尾结构复核。
3. `BinDataCompressed_ROW` 国际服异常单独处理，不能混入国内默认的 870 张普通表。
4. 当前报告是**元数据血缘审计**。完整新版数据导出是否与真实客户端挂载层和 Schema 逐项一致，仍没有得到最终实证。原始游戏记录未公开发布。

输出可用 `python tools/schema_lineage.py --manifest docs/snapshots/pc-1.111.0.177-229314.json --history-root . --output build/schema_lineage_229314.json --summary build/schema_lineage_summary_229314.json` 从仓库复现。
