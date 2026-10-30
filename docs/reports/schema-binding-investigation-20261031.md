# Schema 与奖励字段绑定核对（2026-10-31）

本次接续[引用内容维护](referenced-content-maintenance-20261031.md)，核对维护者补充的 `MESSAGE_CONF`、`TASK_CONF`、`REWARD_CONF`、`SELECT_CONF` Schema。数据比较仍固定于 `data/current.zip`，SHA-256 为 `9fa5d0cecd25ac32335f3d6e9624e49353e5f357f14504c9cdd032002fd1b515`。

**新发现：当前奖励载荷的有无和分组，与历史 `ObtainLimit` 精确对应，支持把旧标量字段误当数组常量索引的结构错配推断。** 这是覆盖全表的 JSON 关联证据；尚未用原始 `.bytes` 重解码，不能据此声称当前奖励已恢复，也不能确认实际运行时选择了哪一份 Schema。

## 资料来源与保存范围

维护者按 Pak 标签提供 Schema 文本。附件中的 Markdown 转义已规范化为 JSON，仅处理行尾反斜杠、HTML 空格实体、NBSP 和布尔字面量外的加粗标记。Pak 标签按维护者声明记录，未独立检验 Pak、完整逻辑路径、挂载选择或原始 `.non` 字节。

与仓库已有 Schema 完全相同的声明不重复保存；两份此前没有对应历史 Schema 的声明保存为：

- [`TASK_CONF.chunk4_3_P.json`](../../data/evidence/schema_samples/TASK_CONF.chunk4_3_P.json)：43 个顶层字段，来自 `Pasted markdown (2).md`。
- [`REWARD_CONF.chunk4_3_P.json`](../../data/evidence/schema_samples/REWARD_CONF.chunk4_3_P.json)：9 个顶层字段，来自奖励附件的第三段 `3.chunk4 3p`。

| 样本 | 收到的 Markdown 附件 SHA-256 | 保存的规范化 JSON SHA-256 |
| --- | --- | --- |
| TASK 3_P | `8e8654aa22e35965f5981576517052fdc098c1efbe78f0ab8d786f24c7c46af5` | `f92e2e897b1f30b3e4a9347e2d2e1e348ca6161b881260c53f7cb84204b5d470` |
| REWARD 3_P | `e8dfc06bd1a03fce6aca13f29c9a3703b45646185edb09f1ccb90f3d82c43de3` | `35830bb48cd3eb727d67f8adfe07b3327155ef65352cb872916141d3d6ccbaf7` |

这些指纹分别标识收到的附件和规范化产物，不是原始 `.non` 的指纹。样本仅用于解释结构差异，不自动参与补充包解析或覆盖当前 Schema。

维护者另列 `REWARD_CONF / 10_P`，并说明其正文被折叠为附件；本次可读取的奖励附件副本包含 base、0_P、3_P 三段完整 JSON，文件结束于 `4.chunk4 10p` 标题。10_P 的独立正文尚未从收到的副本中识别，不把已有三段重新标为 10_P。

## 一、MESSAGE_CONF：字符串索引空间不同

三份声明均有 11 个顶层字段。base 与维护者提供的 3_P 声明相同，当前 ZIP 附带的 Schema 也与之相同；0_P 的差异限于下列四个字段：

| 字段 | Offset | base／3_P | 0_P |
| --- | ---: | --- | --- |
| `myname` | 16 | `EString`，`CompressedSize=4` | `ELocalizedString` |
| `sender` | 20 | `EString`，`CompressedSize=4` | `ELocalizedString` |
| `text` | 24 | `EString`，`CompressedSize=4` | `ELocalizedString` |
| `receive_des` | 40 | `EString`，`CompressedSize=4` | `ELocalizedString` |

所有 `Size` 都是 4，其他七个字段及顺序不变。在所核查的解析器中，`EString` 读取四字节索引后查询本数据文件的常量表，`ELocalizedString` 读取四字节索引后查询传入的本地化表。两者都不是在行中直接读取整段正文。相同宽度可以使错误绑定不立即表现为读取位置错误。

3_P 声明也等于 base，因此不能凭 Schema 相同就断定实际选中了基础 Pak；也不能仅把类型改为 `ELocalizedString` 就认定问题修复。

## 二、TASK_CONF：字段集合、顺序与嵌套结构均有差异

| 来源 | 顶层字段数 | 按所核查解析器计算的顶层存在位字节数 | 关键区别 |
| --- | ---: | ---: | --- |
| base／当前 ZIP 附带 Schema | 64 | 8 | 含 `task_gameplay1`、`task_gameplay2` |
| 0_P | 65 | 9 | 三个新字段排在末尾 |
| 2_P | 65 | 9 | 同三个字段移至中部 |
| 3_P | 43 | 6 | 相比 2_P 少 22 个顶层字段，条件子结构也缩减 |

0_P 与 2_P 的字段集合、类型、数组声明、嵌套定义相同，但 `task_special_structure_dungeon`、`retention_type`、`retention_type_data` 重排，引起 54 个顶层 Offset 变化。字段数相同不代表 Schema 可互换。

base 到 2_P 的八个字符串类型变更为：`name`、`belong_place`、`task_des`、`receive_des`、`accept_condition.text`、`task_condition.text`、`task_condition.des_text`、`task_condition.done_text`，均从 `EString` 改为 `ELocalizedString`。`go_guide.show_text` 在 base 中已经是 `ELocalizedString`。

3_P 的 `task_condition` 从 13 个字段变为 10 个，删去 `des_text`、`count_operate`、`count_reset_cycle`。所以只修改几处文本类型无法得到这份结构。不同布局也可能影响奖励引用、条件及动作字段，必须用实际原始数据核对。

## 三、REWARD_CONF：旧限额被当作奖励数组入口的精确特征

### Schema 对照

位次按 1 起算。Offset 为声明值，不代表压缩记录的固定文件位置。

| 来源 | 顶层字段数 | `RewardItem` 位次 | Offset | 奖励子结构字段数 |
| --- | ---: | ---: | ---: | ---: |
| base／当前 ZIP 附带 Schema | 12 | 12 | 44 | 5 |
| 0_P | 12 | 12 | 44 | 5 |
| 1_P | 13 | 12 | 44 | 5 |
| 3_P | 9 | 9 | 32 | 3 |

base 到 0_P 只改变 `Name`、`DisplayName`、`Description` 的字符串类型。1_P 在末尾增加 `ObtainLimitBySingleContent`，不移动 `RewardItem`。3_P 删去顶层 `ObtainLimit`、`DropChance`、`DropRound`，把第 9 项变为 `RewardItem`；其子结构只保留 `Type`、`Id`、`Count`，删去 `DropWeight` 和 `DropWeight_change_conf`。所有版本的 `ArrayDim` 都为 25，这不表示每个奖励实例实际都有 25 个组件。

9、12、13 个字段在所核查解析器中都对应两字节存在位。这里的关键变化是同一存在位对应了不同字段，不是存在位字节数改变。

### 全表比对结果

审计结果写入 [`content_binding_evidence.json`](../../data/evidence/content_binding_evidence.json) 的 `tables.REWARD_CONF.history_comparisons`。各历史源均记录 Git blob 指纹；关联审计只比较当前表与该历史源的共同 ID。

| 比较 | 当前表 | 历史 0_P | 双向 ID 差集 |
| --- | ---: | ---: | --- |
| 全表 ID 数 | 7,826 | 7,826 | 空 |
| 当前有 `RewardItem`／历史有 `ObtainLimit` | 623 | 623 | 空 |
| 当前无 `RewardItem`／历史无 `ObtainLimit` | 7,203 | 7,203 | 空 |
| 当前为 `[{Type:22,Count:1000000}]`／历史 `ObtainLimit=1` | 611 | 611 | 空 |

其余 12 条也遵循相同规律。按历史 `ObtainLimit` 分组，当前载荷如下：

| 历史限额值 | 行数 | 当前不同载荷数 | 每份载荷组件数 | 当前载荷首项 |
| ---: | ---: | ---: | ---: | --- |
| 1 | 611 | 1 | 1 | `{Type:22,Count:1000000}` |
| 3 | 1 | 1 | 5 | `{Type:2,Id:1,Count:20000000}` |
| 4 | 5 | 1 | 12 | `{Type:10,Id:1070020101,Count:1}` |
| 5 | 5 | 1 | 6 | `{Type:1,Id:100002,Count:10}` |
| 25 | 1 | 1 | 25 | `{Type:4,Id:2501633,Count:1}` |

历史 1_P、2_P 在与当前表的共同 ID 范围内也没有反例。审计显式区分字段缺失、零值、空数组和 JSON `null`，并比较 ID 集合，而不只比较总数。

历史基础层不满足这项对应关系：共同 7,162 条记录中，历史含限额的有 318 条，当前含载荷的有 592 条。因此，这项推断限定于匹配的 0_P 及后续共同范围；报告同时保留基础层的差集和载荷反例。

### 支持的错配方向

所核查的 `ReadArray` 从行中读取四字节常量索引，再到常量表取数组。由此，以下方向同时解释全部观测：

1. 原数据第 9 项仍是旧 `ObtainLimit` 标量。
2. 使用第 9 项为 `RewardItem` 的较短 Schema 读取。
3. 没有限额存在位的行不会输出 `RewardItem`，对应 7,203 条。
4. 有限额时，其数值被当成数组常量索引；同一数值取得同一载荷，形成上述五组。
5. 原本位于第 12 项的真实 `RewardItem` 不在这份九字段 Schema 的遍历范围内。

相反，“3_P 数据被旧 Schema 读取”会让数组入口出现在 `ObtainLimit` 字段；当前表没有这个字段，不能用这一反向模型说明本次完整现象。

**这是结构错配的强证据，尚不是二进制重解码结果。** 当前 ZIP 附带的是 base Schema，也不能证明运行时采用了它。当前 623 份载荷应重新核验；历史奖励仍保留来源和候选身份。本次不修改 `current.zip`、补充包操作或冲突处理决定，`REWARD_CONF/19589` 仍无可信定义。

## 四、SELECT_CONF：字段数相同，顺序仍不兼容

四份声明均有 26 个字段。维护者提供的 3_P 与 2_P 声明相同；当前 ZIP 附带 Schema 与 base 相同。

- base：第 2 项是 `editor_name`，`text` 在 Offset 12，类型为 `EString`；末项为 `system_control_id`。
- 0_P：没有上述两个字段，`text` 在 Offset 8，类型为 `ELocalizedString`；末尾增加 `disable_cond`、`disable_cond_params`。
- 2_P／3_P：把两个 `disable_*` 字段移到 `enable_cond_params` 后、`times` 前。`select_next_dialogue` 的声明 Offset 从 0_P 的 80 变为 88。

因此不能仅校验字段总数或只改 `text` 类型。既有 130 条选项文本候选仍需原始索引与正确本地化表配对验证。

## 解析器依据及下一步

本次检查的代码固定为：

- [CUE4Parse `FRocoBinData.cs`，提交 `2a159ad0`](https://github.com/FabianFG/CUE4Parse/blob/2a159ad0702120db30fdd85c1219dff78e5204b8/CUE4Parse/GameTypes/Tencent/RocoKingdomWorld/Assets/Objects/FRocoBinData.cs)：`ReadRocoString`、`ReadLocalizedString`、`ReadArray`、`ParseStruct`、`ParseNestedStruct`。
- [FModel 调用代码，提交 `05cfbdd1`](https://github.com/4sval/FModel/blob/05cfbdd1648afe2928109b70ab63880a4bc8f7b4/FModel/ViewModels/CUE4ParseViewModel.cs)：`ProcessRocoBinFile` 按同名 `.non` 后缀在 Provider 文件集合中取匹配项，再按数据路径查找 `zh_Hans` 本地化文件。

`ParseStruct` 按 Schema 字段数读取存在位，再按声明顺序读值，不按每个 `Offset` 跳转。数组、嵌套结构和数据行具有各自的常量／数据表定位；不能泛称嵌套字段减少必然串坏后续元素或行。以上结论限定于核查的代码版本，不代表已确认维护者实际使用的 FModel 构建版本。

下一步优先核验实际用于导出的原始 `REWARD_CONF.bytes`：保留来源 Pak 和完整内部路径，将匹配的 Schema 与原始本地化资源一同定位，然后重解并比对五组载荷、缺失明细及 19589。其余三表同理。Schema、数据和本地化可来自不同补丁层，必须核验有效组合，不能仅按 Pak 编号或字段数量选择。

复现现有 JSON 关联审计：

```bash
python tools/content_binding_audit.py --repo . --output build/content_binding_evidence.json
```
