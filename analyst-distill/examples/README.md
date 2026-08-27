# examples/ 样本库（质量示范，非模板）

> **定位**：本目录存放历次蒸馏的**完成品文档**，作用是给新对话的 agent 提供"好产出的样子"（深度手感、标注纪律、结构组织），**不是可复制的内容模板**。
> **铁律**：只学结构与标注纪律，**禁止照搬领域内容**（框架名、阈值、指标、观点一律不得复制到新技能——每个分析师的数值都是其本人的）。
> 无同类样例时（如第一个金工），依赖 `references/acceptance-checklist.md` 验收清单 + 本目录结构最近的样例。

---

## 一、读取时机表

| 阶段 | 有同类样例时 | 无同类样例时 |
|---|---|---|
| Phase 2 框架提取前 | 选一个同类样例，先读 `framework.md` 末尾场景速查和一段代表性框架；必要时再抽读 `indicators.md` / `decision-rules.md` 对应章节 | 选 `strategy-zhangyidong`，只读结构和标注方式，不读全套 |
| Phase 3 技能打包前 | 读同类 `SKILL.md` 的章节组织和路由表；必要时只看 `profile.md` / `views.md` 顶部结构 | 读 `strategy-zhangyidong/SKILL.md` 的结构，不照搬 description |
| Phase 3 写脚本前 | 读 `scripts-template/screen_template.py` + `references/scripts-conventions.md` | 同左（骨架与规范是领域无关的，必读） |
| Phase 4 验证报告前 | 读一个同类 `validation.md` 的五段式结构 | 读 `strategy-zhangyidong/validation.md` 的结构 |

**判定"同类"**：specialty 相同（macro/strategy/fixed-income/quant）或产出形态相同（如都是"仓位+风格"型）。不确定时读结构最全的 zhangyidong。

## 二、索引表（按归档时间倒序）

| 目录 | 领域 | 分析师 | 一句话特点 | 归档时间 |
|---|---|---|---|---|
| `fixed-income-zhangjiqiang/` | 固收 | 张继强（中金→华泰证券） | 五碗面总纲+胜率赔率；年度区间锚逐年下移+六大策略工具排序+股债性价比 20/80 分位切换；首个固收样本（事件时点复算三方对照验证） | 2026-08 |
| `strategy-zhangyidong/` | 策略 | 张忆东（兴业→海通国际） | 主要矛盾→资产定价→结构主线；S3 三重共振+S7 美债链+S8 AI 时钟 | 2026-08 |
| `macro-guolei/` | 宏观 | 郭磊（广发证券） | 总量→结构→择时→配置；M1-BCI-PPI 三因子 | 2026-08 |

> 仅当案例被归档为金样本时，在本表**顶部**插入一行（领域/分析师/一句话特点/归档时间）。

## 三、案例归档约定（可选，与 SKILL.md Phase 5 联动）

默认不要把每位新分析师都写回 `examples/`。当用户明确要求归档，或该案例满足以下条件时，才作为金样本沉淀：

- 产出完整通过 `acceptance-checklist.md`
- 代表一种此前缺失或明显不足的类型模式
- 文档结构、来源标注、验证报告对后续任务有示范价值

归档时执行：

1. **复制文档类 7 文件**进 `examples/{specialty}-{name}/`：
   `SKILL.md` + `references/{framework,indicators,decision-rules}.md` + `assets/{profile,views,validation}.md`
   （`scripts/screen.py` **不复制**——它是领域特定代码，骨架与规范已覆盖脚本质量；如需对照函数写法，读 `scripts-template/screen_template.py`，不要读取成品脚本源码）
2. **更新本 README**：索引表顶部插入新行
3. **不自动更新 domain-adapters.md**：只有当该案例揭示出跨案例稳定模式，并满足 `references/domain-adapters.md` 的"类型模式晋升门槛"时，才更新领域适配器

## 四、质量示范的三份文件分别示范什么

| 文件 | 示范点（学什么） |
|---|---|
| `framework.md` | 分层逻辑、每框架"定义/逻辑/应用/实例"四要素、时点标注、场景速查表 |
| `indicators.md` | 六字段指标表、功能分类、跟踪优先级分级 |
| `decision-rules.md` | 规则 0 分级、阈值量化到可脚本化、S 信号汇总表、数据-规则映射附录 |
| `profile.md` | 机构归属红线、观点验证记录表（✅⏳❓⚠️） |
| `views.md` | 顶部警示语、时间倒序、当前/历史分区、已过期标记、演化主线 |
| `validation.md` | 五段式验证报告、三层来源表、事件三方对照、误报归因 |
| `scripts-template/screen_template.py` | 脚本框架（非完整实现）：工具函数/参数区/五函数结构/JSON schema/`--schema`/四入口 |
