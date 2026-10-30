# PC 1.111.0.177 (229314) 候选数据本地全量验收报告

> **发布状态更新：** 完整数据包现已提交为 [`data/current.zip`](../../data/current.zip)，参见 [PR #10](https://github.com/ikun810/Roco-Kingdom-World-Data-new/pull/10)。下文“未向 GitHub 上传”记录的是原始 QA 执行时的状态；Schema 来源及再分发许可未经独立验证的提示仍然有效。

本报告来自用户已上传的 FModel 合并导出 `Bin(1).zip`，经 `tools/release_candidate.py` 在本地逐个文件校验。**未向 GitHub 上传游戏配置正文或 Pak**。

- 原始上传 ZIP SHA-256：`9fa5d0cecd25ac32335f3d6e9624e49353e5f357f14504c9cdd032002fd1b515`
- 输入文件：**2314 / 2314** 哈希与元数据核验通过；其中普通表 **870**、Schema **870**、本地化 **571**、ROW **3**。
- 普通配置共 **675,341** 条记录，空表 50，JSON 解析错误 0；S1–S4 均存在。
- 七月原始历史目录和当前主分支的数据文件保持原样。
- `source_zip_sha256` 只证明本地审核的 ZIP 与 PR #6 登记的 ZIP 是同一份输入，不证明官方授权或运行时挂载顺序。

## 残留的 Schema 来源问题

- 107 张表出现记录字段未被导出 Schema 声明的现象；结合 PR #7 的历史血缘核对，其中 **33 张表**涉及七月历史没有的 **56 个字段**。
- 对这 33 张表的全部新增字段进行了真实记录检查，统计出出现的行数和 Python JSON 值类型。此操作说明字段确实存在，但**不能仅凭格式证明它与同版本 `.non` 完全匹配**。
- 一张含有参数名式键的表 `ROGUE_CHALLENGE_GLOBAL_CONFIG` 存在 10 处外层记录 key 与数字 `id` 不同；已按字段布局特例保留，不自动删除、重编号或当作解析失败。

### 新版字段优先复核清单（仅元数据）

| 表名 | 普通记录数 | 七月未见字段及其出现的行数 |
| --- | ---: | --- |
| `ACTIVITY_DROP_METHOD_CONF` | 652 | `day_got_limit_type` (62), `week_day_time` (652) |
| `ACTIVITY_PET_CERTIFICATION` | 4 | `fullstar` (2) |
| `ACTIVITY_RECALLBP_CONF` | 5 | `up_bp_name` (5) |
| `ACTIVITY_SEASON_SPRINT_CONF` | 3 | `chasing_reward_title` (1), `exp_chasing_limit` (1), `instruction_desc` (1), `pass_exp_module_desc` (1), `pass_exp_progress_desc` (1), `season_bg_umg_path` (2), `task_group` (1), `window_title` (1) |
| `ALL_RIDE_PET` | 653 | `monitor_data_version` (653) |
| `AREA_FUNC_CONF` | 582 | `ascription_proprity` (6) |
| `BALL_CONF` | 27 | `param_move` (1), `param_surface` (1) |
| `BATTLE_CONF` | 7,298 | `is_pvp_season_music` (1) |
| `BATTLE_PASS_CONF` | 4 | `bp_pass_select` (4) |
| `BUTTON_SETTING_CONF` | 61 | `sort_id` (61) |
| `CHAT_BUBBLE_CONF` | 1 | `item_quality` (1) |
| `FURNITURE_ITEM_CONF` | 269 | `furniture_center_offset` (2) |
| `LEVEL_SKILL_CONF` | 925 | `extra_machine_skill_group_id` (1) |
| `MODEL_CONF` | 3,387 | `resource_inpackage_version` (302) |
| `NORMAL_SHOP_CONF` | 2,060 | `resource_inpackage` (234) |
| `NPC_CONF` | 18,962 | `can_be_bound_and_hidden` (2837) |
| `NPC_REFRESH_CONTENT_CONF` | 39,385 | `first_emerge_skill` (677) |
| `PETBASE_CONF` | 1,147 | `habit_ai_group_info_id` (4), `head_marker_offset` (5) |
| `PET_INFORMATION_CONF` | 10 | `condition_param2` (4) |
| `PET_TOPIC_TYPE_CONF` | 16 | `is_show_in_magic_challenge` (16) |
| `PLANT_GROW_CONF` | 24 | `plant_show_bagitem` (24) |
| `PVP_CONF` | 8 | `end_time` (2), `rule_list` (5), `rule_num` (2), `rule_tips` (2), `start_time` (2) |
| `PVP_RANK_CONF` | 117 | `share_bg` (117) |
| `RELATIONTREE_ANIM_CONF` | 27 | `allow_broadcast` (7), `roleplay_id` (2), `simple_action_id` (1), `single_key` (2), `socialshare_type` (1) |
| `RIDE_SOCKET` | 153 | `skill_socket_pc1` (12), `skill_socket_pc2` (12) |
| `ROLEPLAY_BEHAVIOR_CONF` | 105 | `relationtree_anim_id` (7) |
| `ROLEPLAY_PROP_CONF` | 18 | `related_function_id` (1) |
| `SCENE_STATUS_WPST_CONF` | 31 | `is_afk_wandhold` (2) |
| `SEASON_ADVENTURE_BADGE_LEVEL` | 24 | `badge_level_reward` (12), `badge_level_up` (12), `star_icon` (12) |
| `SEASON_HANDBOOK_CONF` | 4 | `shining_collect_task` (1) |
| `TREASURE_ITEM_CONF` | 10 | `if_last_safety_net` (10) |
| `WEEKLY_CHALLENGE_EVENT_CONF` | 41 | `extra_reward_limit` (12), `extra_star` (12), `reward` (12) |
| `WISH_EXCHANGE_CONF` | 51 | `wish_exchange` (26) |

完整的字段类型分布、历史来源候选及记录数见 [机器可读 QA 报告](pc-1.111.0.177-release-qa.json) 和 [Schema 血缘报告](pc-1.111.0.177-schema-lineage.md)。报告不包含任何具体游戏记录或本地化文本。

## 发布门槛

**技术文件完整性：已通过**；**Schema 来源一致性：部分待核验**；**公开再分发许可：未确认**。

本次仅适合建立**用户本地完整候选包**。要把全部游戏配置 JSON 上传到公开 GitHub，必须先明确合法再分发范围并完成重点表对应同版本 Schema 的检查。在那之前，仓库仅存原创工具及技术元数据。

自动化 CI 只检查已发布的报告元数据与七月历史一致性；不能访问或重新校验用户私有 ZIP。本地候选包的结构与运行方法见 [操作手册](../RELEASE_CANDIDATE.md)。
