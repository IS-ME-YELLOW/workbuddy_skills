---
name: analyst-distill
description: 分析师蒸馏流水线技能（自包含指令包）。当需要把任意领域卖方分析师（宏观/策略/固收/金工/行业）、买方或机构分析师的研究框架蒸馏为可执行 skill 辅助选股/配置时使用。本包不依赖对话历史：自带验收清单、脚本规范与骨架、示范样本库，任何平台/新对话加载本技能即可达到与既有完成品同等的蒸馏质量。覆盖完整流程：资料收集（限定时窗）→ 框架提取（framework/indicators/decision-rules）→ 技能打包（SKILL.md + screen.py + profile）→ 观点校验（views.md 时效分离）→ 信号验证（validation.md）。触发词："蒸馏分析师""分析师转skill""把XX的框架做成技能""蒸馏XX的框架""框架转技能"等。
agent_created: true
---

# 分析师蒸馏流水线（analyst-distill）—— 自包含指令包

将卖方/买方/机构分析师公开研究蒸馏为可执行选股/配置 skill 的标准流程。已完成原型：郭磊(宏观)、张瑜(宏观)、张忆东(策略)，本包固化其方法、模板与验收标准。

## 零、自包含声明（先读）

本Skill为自包含指令包，不依赖平台与上下文环境。质量保障由三层构成：

| 层 | 载体 | 作用 |
|---|---|---|
| 流程骨架 | 本 SKILL.md（五阶段 + 红线） | 告诉 agent 做什么、按什么顺序 |
| 验收标准（领域无关） | `references/acceptance-checklist.md` | 告诉 agent **什么样的产出算合格**（逐条勾选，任何领域通用） |
| 示范样本（领域相关） | `examples/` + `references/scripts-conventions.md` + `references/domain-adapters.md` | 告诉 agent "好产出长什么样"（学结构与纪律，禁止照搬内容） |

> **核心机制**：验收清单管质量下限（可扩展到任意领域），examples 提手感（只对已有类型），回填机制让样本库随蒸馏轮次自适应增长（覆盖开放空间）。

## 一、结构

```
analyst-distill/
├── SKILL.md                                  # 本文件：入口（流程 + 红线）
├── references/
│   ├── acceptance-checklist.md               # ★ 九节逐条验收清单（领域无关，强制标准）
│   ├── scripts-conventions.md                # ★ screen.py 编写规范（架构 + JSON schema + 自测）
│   └── domain-adapters.md                    # 领域翻译要点 + 新领域自适应路径 + 平台降级方案
└── examples/
    ├── README.md                             # 样本库使用规则 + 读取时机表 + 回填约定
    ├── scripts-template/screen_template.py   # ★ 不完整代码骨架（框架就位，计算逻辑留占位）
    ├── macro-guolei/  macro-zhangyu/  strategy-zhangyidong/   # 完成品文档示范
```

## 二、使用前必读（新对话读取顺序）

1. 读完本文件（流程 + 红线）
2. 开始 Phase 2 前：读 `references/acceptance-checklist.md` §2-§4（产出标准）+ 按 `examples/README.md` 读取时机表选读示范样本
3. 开始 Phase 3 前：读 §1/§5/§6/§8 + `references/scripts-conventions.md` + `examples/scripts-template/screen_template.py`
4. 开始 Phase 4 前：读 §7 + 本文件 Phase 4 操作陷阱 + 同类 `validation.md` 示范
5. 遇到"新领域/缺数据源/无校验工具"时：读 `references/domain-adapters.md`

## 三、前置约定（与用户确认后再开工）

1. **产品形态**：先做 Skill，后续再集成 Expert
2. **技能结构**：每位分析师一个独立 skill，命名 `analyst-{specialty}-{name}`（specialty: macro/strategy/fixed-income/quant，或其他实际领域）
3. **输出格式**：框架 + 可执行脚本
4. **安装位置**：用户级 `~/.workbuddy/skills/`
5. **资料窗口**：近 36 个月（明确起止月份）
6. **工作流**：每完成一个 phase 向用户汇报（找了什么资料/写了什么文档/文档概要），等确认再继续（用户明示"免确认直接跑"除外）

## 四、五阶段流水线

### Phase 1 资料收集
- 多轮检索（至少 4 组主题：分析框架方法论 / 核心观点(逐年) / 驱动力与投资逻辑 / 择时与定价方法）
- 新领域（固收/金工/买方/行业等）**加一轮"领域特有跟踪指标体系"检索**（该分析师常用的指标/数据/模型工具），作为 indicators.md 原料
- 覆盖整个 36 个月窗口（含最新观点——在窗口末端补一轮"最新观点"检索）
- 量化细节（回测参数、阈值）必须单独一轮检索拿到原文细节，并**记录出处**（哪篇报告/哪期/哪句话）；无法核对到原文的数字一律标"推断"，不得写成引用
- 输出：资料清单汇报（检索主题/主要收获/框架清单/指标清单/决策规则），等用户确认
- **验收**：汇报含框架/指标/规则三清单；窗口全覆盖；出处可追溯

### Phase 2 框架提取
- 写入 `~/.workbuddy/skills/analyst-{specialty}-{name}/references/` 三份文档：
  - `framework.md`：框架分层（**按该分析师自己的方法论主体分层，不强套已有领域**），每个框架含定义/逻辑/选股应用/窗口内实例 + 场景调用速查表
  - `indicators.md`：指标库（口径/频率/所属框架/阈值）+ 日常跟踪优先级
  - `decision-rules.md`：可执行规则（计算步骤、阈值、信号触发表），**阈值必须量化**
- **来源标注（强制，禁止"虚假精确"）**：三份文档顶部放统一图例（✅ 原文 / ⚠️ 外推 / ❌ 推断），每个阈值、权重、参数、回测数字逐条标注：
  - ✅ 原文 = 分析师公开研究中明确给出的数值/口径（尽量注明出处报告）；
  - ⚠️ 外推 = 有公开依据但具体数值/分档未经逐字核对（注明"以原文复核"）；
  - ❌ 推断 = 分析师未公布、为实现可脚本化而作的假设（等权、窗口长度、滤波 λ 等）——**必须写明"最小假设，可替换"**；
  - 回测/绩效数字一律加"~"并注明"取自公开报告，以原文为准"；观点实例的具体小数（如某期因子贡献值）不得杜撰，写"以当期报告原文为准"占位
- 观点时效性处理：把时点观点单独拆到 `assets/views.md`，decision-rules 中只留"观点更新模板"结构，framework 实例加时点标注
- **验收**：对照 `references/acceptance-checklist.md` §2-§4 逐条勾选，全过才算完成；未过项须修复或写明理由
- 等用户确认

### Phase 3 技能打包
- `SKILL.md`：YAML frontmatter（name/description 第三人称含触发词/`agent_created: true`，**description 禁止尖括号**）+ 工作流（先读 views.md 最新观点→体检→择时→风格→配置）+ 数据获取（westock-data/westock-tool/neodata）+ 红线
- `scripts/screen.py`：**复制 `examples/scripts-template/screen_template.py` 骨架 → 按 `references/scripts-conventions.md` + decision-rules.md 填充**。纯标准库；五函数结构；参数区注释块每常量带来源分级；`--data` 真实数据 / 默认演示模式（明确标注合成数据）/ `--json-out` 布尔标志
- `assets/profile.md`：分析师档案（执业编号/团队/风格/与其他分析师差异）+ 36 个月观点验证记录（✅/⏳/❓/⚠️ 分级）+ **机构归属变化红线**
- `assets/views.md`：观点快照区（顶部警示语"使用前核对最新观点"、时间倒序、旧快照标"已过期"、演化主线）
- 用 skill-creator 的 `package_skill.py` 校验（必须输出 "Skill is valid"）；无该校验工具时按验收清单 §1/§9 人工勾选替代
- 运行 `screen.py` 演示模式验证输出（demo 下每信号至少触发一次）
- **验收**：对照 `references/acceptance-checklist.md` §1/§5/§6/§8 逐条勾选；校验通过；演示模式跑通
- 向用户汇报（写了什么文档/脚本功能/校验结果），等确认

### Phase 4 信号验证
- 用 westock-data / westock-tool 拉取窗口内真实历史数据，回填 screen.py 验证 S 信号与真实行情的对应
- 与 views.md 观点快照对照，标记验证状态（profile.md 中 ✅/⏳）
- **事件时点复算（核心方法）**：不要只看最新快照。对窗口内每个关键事件月份，用"截至该月"的数据窗口（`history` 是"字段→月份数组"的转置结构，按月份索引切片即可）复算全部 S 信号，与①分析师同期观点 ②前瞻 1M/3M 真实行情三方对照。该时点的 `extras`（风格/阶段类）需按叙事推断并标注 ⚠️。
- **定位提醒（重要）**：验证的目的是**检验框架是否忠实还原分析师思维**（信号方向与分析师判断/历史事件对得上），**不是追求回测绩效**。
  回测跑出来的收益只证明"我们实现的版本"（含 ❌ 推断参数）的表现，**不能反推分析师真实参数**；
  报告必须写明：绩效数字 ≠ 分析师框架的绩效，推断参数是主要不确定来源
- **数据缺口如实记录（三层来源标注）**：拿不到真实数据的因子用 ✅westock / ⚠️观点锚点+线性插值 / ❌工程代理 三级标注，不得用合成值冒充验证结论。误报点必须归因（数据口径差异 vs 框架边界 vs 原文含糊），并在结论中写明"必要非充分"类框架教训（例：三重共振是空间条件，缺时间/催化时仍会误报→决策规则需叠加确认条件）。
- **known pitfalls（批量扩展必看）**：
  - screen.py 的 `--json-out` 是布尔标志（stdout 输出 JSON），不是文件路径参数
  - `package_skill.py --out` 会被当作输出目录（产物在 `--out/<name>.zip`），需手动 mv 回目标路径；Windows 下 `--out` 开头目录删除会被 safe-delete 拦截，用 PowerShell `Remove-Item -LiteralPath` 处理
  - SKILL.md frontmatter `description` 禁止含尖括号 `<` `>`（校验失败），写成"高于/低于 X%"
  - westock-data 返回：profit/financing/m12 为嵌套 `{"sections":[[...]]}` 且倒序，需 flatten+反转；premium_curve 为多个乱序 sections，需按 EndDate 排序重建序列；日频数据→月均时注意月末截断
  - 口径差异警示：同一指标不同数据源绝对水平可能背离（例：westock ERP 3% vs 分析师引用 5.3%），仅分位/方向可用，绝对阈值触发不可跨口径比对——必须在 `_meta` 与 validation.md 双处标注
- **验收**：对照 `references/acceptance-checklist.md` §7 逐条勾选：五段式报告、三层来源表、≥5 事件三方对照、误报归因、口径差异双处标注
- 写 `assets/validation.md`，更新 profile.md 验证状态，重新打包 zip（同步 validation.md）
- 向用户汇报（拉了哪些数据/怎么回填/验证结论/误报），等确认

### Phase 5 批量扩展与回填
- 原型确认后，按相同流水线批量蒸馏其余分析师
- 跨分析师做差异化定位（如 12 位分析师 = 宏观3/策略3/固收3/金工3），避免框架重复
- **回填机制（强制收尾步骤，样本库自适应增长的核心）**，每位分析师完成后：
  1. 复制文档类 7 文件进 `examples/{specialty}-{name}/`（SKILL.md + references×3 + assets×3；**不复制 screen.py**——骨架与规范已覆盖脚本质量）
  2. 更新 `examples/README.md` 索引表（顶部插入新行）
  3. 向 `references/domain-adapters.md`"已有领域翻译要点"补写该领域要点
  4. 新领域完成首例后：该类型从此有 example，后续同类型蒸馏读它

## 五、模板要点（从完成品固化）

- 决策规则必须能量化到"可脚本化"：调仓频率、得分阈值、σ 倍数、分位阈值、滤波方法
- **一切阈值/权重/参数带来源标注**（✅/⚠️/❌），推断值写明"最小假设，可替换"；禁止把推断数字写成原文引用
- 观点与规则严格分离：信号计算不依赖观点快照；冲突时优先遵循信号并说明分歧
- screen.py 保持纯标准库（HP 滤波共轭梯度 ~30 行，避免 numpy 依赖）；结构与质量见 `references/scripts-conventions.md`
- A 股惯例：涨红跌绿、货币 ¥
- 每次 phase 完成写入 `.workbuddy/memory/YYYY-MM-DD.md`（记录决策与产出）

## 六、红线与注意事项（全局）

1. **机构归属变化**：分析师任职机构变更（离职/跳槽）是引用红线——观点须注明任职期归属，profile.md 单独记录，禁止混用
2. **观点时效性**：任何输出先核对 views.md 最新观点；过期观点不得当作当前判断
3. **禁止虚假精确**：无法核对原文的数字一律"推断"标注；回测数字加"~"并注出处
4. **验收清单是强制标准**：每个 phase 产出后勾选对应章节，未过项修复或注明理由，不得静默跳过
5. **examples 是示范非模板**：只学结构与纪律，禁止照搬其他分析师的阈值/框架名/观点
6. **平台降级**：无数据源/无校验工具时按 `references/domain-adapters.md` 降级执行，如实标注"数据源不可用"，不得伪造数据冒充验证

## 七、平台分层声明

- **平台无关核心（任何平台自包含）**：本 SKILL.md（流程）+ acceptance-checklist.md（验收）+ scripts-conventions.md + screen_template.py（脚本规范与骨架）+ examples/（示范样本）
- **平台增强项（有则用，无则降级）**：westock-data/westock-tool/neodata（数据源）、package_skill.py（机器校验）、`~/.workbuddy/skills/` 安装机制
- 降级路径详见 `references/domain-adapters.md` §三
