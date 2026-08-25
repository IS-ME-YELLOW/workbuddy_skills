# screen.py 脚本编写规范（Scripts Conventions）

> **定位**：规定蒸馏产出的 `scripts/screen.py` 必须达到的架构与质量标准，保证任意新对话产出的脚本与既有三份（guolei/zhangyu/zhangyidong）**同框架、同质量**。
> **配套**：`examples/scripts-template/screen_template.py` 是**不完整骨架**（函数签名、参数区格式、JSON schema 已就位，计算逻辑留占位）。新任务的标准做法 = **复制骨架 → 按本规范 + decision-rules.md 填充计算函数 → 自测通过**。
> 骨架缺"实现细节"，本规范缺"结构约束"，两者互补，缺一不可。

---

## 1. 硬性约束（违反即返工）

- [ ] 纯标准库：`argparse / json / math / statistics / sys / bisect / datetime` 等。**禁止** pandas/numpy/scipy
- [ ] 单文件、可独立运行（`python screen.py` 直接出演示输出）
- [ ] 不依赖网络、不依赖数据源 SDK——数据通过 `--data <json>` 注入，脚本只做计算与渲染
- [ ] A 股惯例：涨红跌绿（输出/渲染用色时）、货币 ¥
- [ ] 所有魔法数字集中在**参数区**（见 §2），函数体内不散落裸阈值

## 2. 参数区注释块（文件顶部，紧接 imports）

每个信号阈值常量必须带**来源分级**，与 decision-rules.md 图例一致。格式示例：

```python
# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断）
# ------------------------------------------------------------
# S1 风险溢价择时
ERP_HIGH = 0.05        # ✅ 原文：A股 ERP 高于 5% 高性价比区
ERP_TOP_WARN = 0.00    # ✅ 原文：历次牛市风险溢价回到零 = 顶部预警
ERP_HIGH_BAND = 0.08   # ⚠️ 外推：沪深300 ERP 8% 为强性价比（依公开访谈，以原文复核）
HSI_PE_CHEAP = 11.0    # ✅ 原文：恒指前瞻 PE 10-11 倍为估值洼地
HSI_PE_FULL = 15.0     # ❌ 推断：最小假设可替换——满估值分界（分析师未给明确值）
# S3 三重共振
SHORT_RATIO_HIGH = 0.18  # ✅ 原文：卖空占比高于 18% 高位杀空
# ... 每个阈值一行，格式统一：常量名 = 值  # 分级：来源说明
# ============================================================
```

- **分级规则**：✅ 必须能指到原文出处；⚠️ 注明"以原文复核"；❌ 必须写"最小假设，可替换"
- 参数区与 decision-rules.md **逐条对应**（同名规则用同阈值），验收时双向核对

## 3. 五函数结构（与骨架一致，不得改名/删减）

| 函数 | 职责 | 输入 → 输出 |
|---|---|---|
| `compute_<signal>`（每信号一个，如 `compute_s1`） | 纯计算：读 history 窗口 → 返回 (triggered, detail, strength) | `(hist: dict, params: dict) → (bool, str, str)` strength ∈ strong/mid/direction |
| `aggregate_signals(results, extras)` | 汇总各信号 → 仓位/结构/配置建议 | `results: list[dict] → dict` |
| `render_report(signals, positions, extras)` | 人类可读报表 | → `str` |
| `demo_data()` | 合成演示数据（明确标注"合成"） | → `(history, extras)` |
| `main()` | argparse 三入口 + 组装全流程 | → 打印/JSON |

- **数据层与计算层分离**：所有信号函数只吃 `history` 字典切片（字段→月份数组），不直接解析原始数据文件
- history 切片按月份索引（`history[field][:idx]`），**最新在末尾**——事件时点复算依赖此约定

## 4. 输入 JSON schema（`--data` 参数）

```jsonc
{
  "history": {           // "字段 → 月份数组" 转置结构，升序，最新在末尾
    "erp_a":    [0.032, 0.031, ...],
    "m1_yoy":   [1.2, 1.5, ...],
    "...":      [...]    // 字段清单由 decision-rules.md 数据-规则映射附录决定
  },
  "extras": {            // 风格/阶段类单值（如南向风格成长/价值、AI 阶段硬件/应用）
    "south_style": "growth"
  },
  "_meta": {             // 数据来源说明（Phase 4 回填时写，演示模式可省略）
    "erp_a": "westock premium_curve 日频→月均，口径与分析师引用值不同，仅分位/方向可用"
  }
}
```

## 5. 输出 JSON schema（`--json-out` 布尔标志 → stdout）

```jsonc
{
  "as_of": "2026-08",
  "demo": true,                      // 是否演示模式（合成数据）
  "signals": [
    {"id": "S3", "name": "港股三重共振", "triggered": true,
     "detail": "恒指PE 10.5<11 + 南向为正 + 利润18.7%改善 → 3/3",
     "strength": "strong"}
  ],
  "n_triggered": 5, "total": 12,
  "positions": {"仓位": "...", "结构": "...", "港股": "..."},
  "extras": {"south_style": "growth"}
}
```

## 6. 自测要求（交付前必须全部通过）

- [ ] `python screen.py`（演示模式）无报错、输出完整、明确标注"合成数据"
- [ ] `python screen.py --data <json>` 与真实数据跑通，缺字段时报**明确错误**（哪个字段缺失）
- [ ] `python screen.py --data <json> --json-out` 输出可被 `json.load` 解析
- [ ] 每个 `compute_<signal>` 在 demo 数据下至少触发过一次（覆盖触发路径）且能测到未触发路径
- [ ] 阈值与 decision-rules.md 双向核对一致

## 7. 常见陷阱（历次蒸馏踩过）

- `--json-out` 是**布尔标志**（JSON 打到 stdout），不是文件路径参数
- history 是转置结构：切片按 `field[:idx]`，**不是**按行取月份
- 日频→月均注意月末截断；数据源倒序必须反转后再入库
- 演示数据量 ≥ 30 个月且覆盖触发/未触发两个路径，否则无法自测
- 数值格式化：百分比显示统一 `f"{x*100:.1f}%"`，避免 0.1 vs 10% 混乱
- `package_skill.py --out` 会被当作输出目录（产物在 `--out/<name>.zip`），需手动移动回目标路径；Windows 下 `--out` 开头目录删除可能被 safe-delete 拦截，用 PowerShell `Remove-Item -LiteralPath` 处理
- SKILL.md frontmatter `description` 禁止含尖括号 `<` `>`（校验失败），阈值写成"高于/低于 X%"
- westock-data 返回结构要先归一化：profit/financing/m12 可能是嵌套 `{"sections":[[...]]}` 且倒序，需 flatten+反转；premium_curve 可能是多个乱序 sections，需按 EndDate 排序重建序列
- 同一指标不同数据源的绝对水平可能背离（例：westock ERP 3% vs 分析师引用 5.3%）；仅分位/方向可用时，绝对阈值触发不可跨口径比较，必须在 `_meta` 与 validation.md 双处标注
- 工具函数必须过滤 None：窗口末端/次月数据未发布会让末值为 None，`get/trend_up/trend_down/recent_avg/pct_rank` 若直接比较会抛 TypeError；统一加 `_clean()` 剔除 None，`get()` 回溯最近有效值
- 警惕文件后部的重复函数定义覆盖前面的修复；交付前用 `rg "^def "` 检查同名函数
- data.json 建议内嵌 `months` 数组（升序、最新在末尾）：事件时点复算需要月份标签做切片与季节性信号；由 as_of 回推构造时注意 append/insert 方向
- REQUIRED/OPTIONAL 字段分离：无公开数据源的字段放 OPTIONAL，对应信号优雅降级为"缺字段"提示，不得阻塞整体计算
- 历史复算的区间锚前视偏差要显式标注：若分析师区间锚逐年大幅移动，统一用最新区间回算历史会失真；严格做法是分段切换区间参数
