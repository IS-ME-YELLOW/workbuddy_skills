# Phase 4 验证脚本编写规范（phase4-scripts-conventions.md）

> 定位：规范【Phase 4 验证脚本怎么写】。成品 skill 的 `screen.py` 编写规范见
> `scripts-conventions.md`（两者配套：screen 管运行时信号计算，本文件管验证工具链）。
> 配套模板：`examples/scripts-template/phase4_fetch_data_template.py`（A 类骨架）、
> `examples/scripts-template/phase4_validate_events_template.py`（B 类骨架）。

## 一、两类脚本与产物契约

Phase 4 验证由**两个职责阶段**组成，通过一个契约文件（`macro_real.json`）解耦：

| 类型 | 固定名（入成品 skill 的 scripts/） | 职责 | 可通用度 |
|---|---|---|---|
| A 类·数据准备 | `phase4_fetch_data.py` | 读原始数据 → 组装 `assets/data/macro_real.json` | 每分析师必写（指标集不同），结构受本规范约束 |
| B 类·事件复算 | `phase4_validate_events.py` | 对每个事件时点复算信号，三方对照 → `assets/data/signalcheck.json` | 从模板复制，仅改三处 |

**分离式是唯一标准形态**：历史上出现过单脚本混合形态（李超/刘晨明/张瑜）与通用传参形态
（fi_validate 一份服务两位分析师），均属演进中间态。分离的好处：B 类只依赖
`screen.py` 的函数契约，与分析师无关，可完全模板化；A 类产出被两个消费者复用
（`screen.py --data` 跑最新快照 + B 类做事件切片复算）。

**脚本直接写进成品 skill 的 `scripts/`，不落工作区**——工作区只留
`.workbuddy/tmp_{analyst}_{source}.txt` 原始数据（体积大、可重拉、不入包）。
入包的理由：观点更新工作流需要重跑验证；A 类的数据映射（哪个接口、哪些锚点）
是 skill 的核心 IP，不入包则 validation.md 的数字跨环境不可复现。

## 二、统一六步流程（任何领域相同）

```
Step 1  拉原始数据    westock CLI → {workspace}/.workbuddy/tmp_{analyst}_{source}.txt 落盘
Step 2  A 类脚本      skill/scripts/phase4_fetch_data.py → assets/data/macro_real.json
Step 3  最新月快照    python scripts/screen.py --data assets/data/macro_real.json --json-out
Step 4  EVENTS 事件表 ≥5 条（月份/事件名/同期观点+✅⚠️分级/预期信号如 "S3+S5"）
Step 5  B 类脚本      skill/scripts/phase4_validate_events.py → assets/data/signalcheck.json
Step 6  落盘          validation.md 五段式 → profile.md 状态标记 → 重新打包 zip
```

## 三、A 类规范（phase4_fetch_data.py，每分析师必写）

**硬性约束**：纯标准库；`MONTHS` 显式构造 + `assert` 长度（统一窗口如 44 个月）；
文件头 docstring 写明三层来源与输出文件；输出 `{as_of, history, extras, _meta}`。

**函数分层**（顺序固定）：

1. **通用工具层**（从模板直接复制，勿改）：`flatten`（解 westock 嵌套 sections）、
   `month_of`（20230131 → "2023-01"）、`ffill`（按月前填）、`anchor_series`（锚点线性插值）、
   `monthly_avg_from_kline`（日频/周频 K 线 → 月均）
2. **加载层 `load_*()`**：每个 westock 数据源一函数，✅ 标注；docstring 写明
   "接口名 → 字段名 + 解析要点（倒序/嵌套/日频月均）"
3. **锚点层 `ANCHORS`**：`{month: value}` 字典，⚠️ 标注；**每个锚点须能指到分析师
   原文出处**（哪篇报告哪个数字），经 `anchor_series` 插值成整段序列
4. **代理层 `build_proxies()`**：❌ 标注，每条写"最小假设，可替换"
5. **组装层 `build_macro_json()`**：合并三层 → history（字段→月份数组，转置结构）；
   `_meta` **逐字段**写来源（✅/⚠️/❌ + 一句话说明）

**跑完必须打印缺口检查**：逐字段统计 None 月份，缺口大的字段在 validation.md 中如实降级。

## 四、B 类规范（phase4_validate_events.py，从模板复制）

**核心纪律：`import screen` 复用 calc_sN，禁止重写计算逻辑**——保证验证逻辑与
技能逻辑是同一份代码。V2 布局下 B 类与 screen.py 同住 `scripts/`，
`import screen` 直接可用（无需 sys.path.insert）。

**内置通用函数**（模板已完整实现，勿改）：

| 函数 | 职责 |
|---|---|
| `window_at(macro, month)` | 截至该月的无前视切片：`{f: arr[:idx+1]}`（事件月含当月——决策时点可得） |
| `run_signals(screen, h, extras)` | 动态发现 `calc_s1..calc_sN` 并遍历 |
| `fwd_ret(values, idx, n)` | 前瞻 n 个月收益，**次月起算**，越界 None |
| `align_grade(trig_ids, all_sigs, expect)` | align / partial / conflict / n/a 四档 + 数据缺失降级豁免 + `S\d+` 正则（防 "S1" 误命中 "S11"） |

**仅三处需按分析师修改**：
1. `EVENTS` 表——`{month, event, view(含✅/⚠️分级), expect}`，≥5 条
2. `infer_extras(month)`——时点 extras 按叙事推断，⚠️ 标注
3. 前瞻标的——权益类用股指收盘价算涨跌%（`FWD_UNIT="pct"`）；
   固收类换成 10Y 收益率字段算 bp（`FWD_UNIT="bp"`）

**配套硬约束**：calc_sN 统一签名 `fn(h, extras)`（消除个别脚本"某函数不吃 extras"
的特判）；B 类输出须含最新月全信号快照（对应 validation.md"实时快照"节）；
回测可选，启用则必须声明"绩效 ≠ 分析师框架绩效"。

## 五、命名与路径约定

| 产物 | 位置 | 命名 |
|---|---|---|
| A 类·数据准备脚本 | 成品 skill `scripts/` | `phase4_fetch_data.py`（固定名） |
| B 类·事件复算脚本 | 成品 skill `scripts/` | `phase4_validate_events.py`（固定名） |
| macro 数据快照 | 成品 skill `assets/data/` | `macro_real.json`（去分析师前缀，目录即命名空间） |
| 事件复算证据 | 成品 skill `assets/data/` | `signalcheck.json` |
| 原始数据（不入包） | 工作区 `.workbuddy/` | `tmp_{analyst}_{source}.txt` |

## 六、输出 JSON schema

**macro_real.json**（A 类产出，即 screen.py `--data` 输入）：
```json
{
  "as_of": "2026-08",
  "history": {"<field>": [44 个月度值, 最新在末尾, 缺失为 null]},
  "extras": {"<风格/阶段类单值>": "..."},
  "_meta": {"<field>": "✅ westock：接口→字段 / ⚠️ 锚点：出处 / ❌ 代理：最小假设"}
}
```

**signalcheck.json**（B 类产出，validation.md 的事件对照依据）：
```json
{
  "analyst": "<name>", "as_of": "2026-08",
  "events": [
    {"event": "...", "month": "2024-03", "view": "...", "view_grade": "✅/⚠️",
     "expect": "S3+S5", "triggers": ["S3", "S5"],
     "trigger_details": [{"id": "...", "name": "...", "detail": "...", "strength": "..."}],
     "align": "align/partial/conflict/n/a",
     "fwd_1m": "+7.1%", "fwd_3m": "+11.6%"}
  ],
  "latest_snapshot": [{"id": "...", "name": "...", "triggered": true, "detail": "...", "strength": "..."}]
}
```

## 七、常见陷阱（历次蒸馏踩过）

1. **westock 返回结构**：`{"sections": [[...]]}` 嵌套须 `flatten` 解包；数据倒序
   （最新在前），组装时须反转为月份升序；premium_curve 返回 76 个乱序 section，
   按 EndDate 去重排序后重建
2. **None 过滤**：日频月均时先过滤 None 再求均值，否则整月被污染为 None
3. **`S\d+` 正则**：对齐判定必须用正则精确匹配信号 id，裸字符串 "S1" in "S11" 会误命中
4. **extras 签名**：calc_sN 一律 `fn(h, extras)`，混用 `fn(h)` 会导致 B 类遍历崩溃
5. **Windows 陷阱**：package_skill.py 的 `--out` 参数固定生成到 `./--out/` 子目录，
   打包后须移动 zip 并清理该目录（`--` 开头路径 rm 会被 safe-delete 拦截，用
   PowerShell `Remove-Item -LiteralPath`）；`/tmp` 重定向在 Windows Python 下不可见，
   中间产物一律写工作区内路径
6. **无前视纪律**：事件月数据窗口含当月（决策时点可得），前瞻收益从次月起算；
   `extras` 时点推断只允许用"截至该月"已知信息
7. **口径差异**：同一指标 westock 口径与分析师引用值可能不同（如 ERP 绝对水平），
   信号只用分位/方向；口径差异在 `_meta` 与 validation.md 结论**两处**标注
