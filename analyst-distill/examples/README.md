# examples/ 样本库（质量示范，非模板）

> **定位**：本目录存放历次蒸馏的**完成品文档**，作用是给新对话的 agent 提供"好产出的样子"（深度手感、标注纪律、结构组织），**不是可复制的内容模板**。
> **铁律**：只学结构与标注纪律，**禁止照搬领域内容**（框架名、阈值、指标、观点一律不得复制到新技能——每个分析师的数值都是其本人的）。
> 无同类样例时（如第一个金工），依赖 `references/acceptance-checklist.md` 验收清单 + 本目录结构最近的样例。

---

## 一、读取时机表

| 阶段 | 有同类样例时 | 无同类样例时 |
|---|---|---|
| Phase 2 框架提取前 | 读同类 `framework.md` + `indicators.md` + `decision-rules.md` | 读 `strategy-zhangyidong`（结构最全）学标注纪律与深度 |
| Phase 3 技能打包前 | 读同类 `SKILL.md` + `profile.md` + `views.md` | 读 `strategy-zhangyidong` |
| Phase 3 写脚本前 | 读 `scripts-template/screen_template.py` + `references/scripts-conventions.md` | 同左（骨架与规范是领域无关的，必读） |
| Phase 4 验证报告前 | 读同类 `validation.md` | 读 `strategy-zhangyidong/validation.md` |

**判定"同类"**：specialty 相同（macro/strategy/fixed-income/quant）或产出形态相同（如都是"仓位+风格"型）。不确定时读结构最全的 zhangyidong。

## 二、索引表（按回填时间倒序）

| 目录 | 领域 | 分析师 | 一句话特点 | 回填时间 |
|---|---|---|---|---|
| `fixed-income-zhangjiqiang/` | 固收 | 张继强（中金→华泰证券） | 五碗面总纲+胜率赔率；年度区间锚逐年下移+六大策略工具排序+股债性价比 20/80 分位切换；首个固收样本（事件时点复算三方对照验证） | 2026-08 |
| `strategy-fujingtao/` | 策略 | 傅静涛（申万宏源） | 看中期做短期；牛市三拼图+两段论；长/中/短期性价比三层体系+供给出清+存款搬家刻度链 | 2026-08 |
| `strategy-liuchenming/` | 策略 | 刘晨明（天风→广发证券） | 三类资产+利润增速差值；百日线再布局+S3 拥挤度双向+财政-PPI-ROE 传导 | 2026-08 |
| `macro-lichao/` | 宏观 | 李超（浙商证券） | 决策层四层次框架；中美事件互斥开关 + 10Y 区间锚 + K型杠铃 | 2026-08 |
| `strategy-zhangyidong/` | 策略 | 张忆东（兴业→海通国际） | 主要矛盾→资产定价→结构主线；S3 三重共振+S7 美债链+S8 AI 时钟 | 2026-08 |
| `macro-zhangyu/` | 宏观 | 张瑜（华创证券） | 存款剪刀差领先性；三螺旋五信号计分板 | 2026-08 |
| `macro-guolei/` | 宏观 | 郭磊（广发证券） | 总量→结构→择时→配置；M1-BCI-PPI 三因子 | 2026-08 |

> 新完成一位分析师后，在本表**顶部**插入一行（领域/分析师/一句话特点/回填时间）。

## 三、回填约定（强制，与 SKILL.md Phase 5 联动）

每次完成一位分析师的蒸馏后，收尾步骤必须：

1. **复制文档类 7 文件**进 `examples/{specialty}-{name}/`：
   `SKILL.md` + `references/{framework,indicators,decision-rules}.md` + `assets/{profile,views,validation}.md`
   （`scripts/screen.py` **不复制**——它是领域特定代码，骨架与规范已覆盖脚本质量；如需对照函数写法，读 `scripts-template/screen_template.py`）
2. **更新本 README**：索引表顶部插入新行
3. **回填领域要点**：向 `references/domain-adapters.md`"已有领域翻译要点"节补写该领域的分层/信号形态/数据侧重/产出建议
4. **无同类样例的领域完成首例后**：该领域从此有 example，domain-adapters.md 补"新领域自适应路径"验证心得

## 四、质量示范的三份文件分别示范什么

| 文件 | 示范点（学什么） |
|---|---|
| `framework.md` | 分层逻辑、每框架"定义/逻辑/应用/实例"四要素、时点标注、场景速查表 |
| `indicators.md` | 六字段指标表、功能分类、跟踪优先级分级 |
| `decision-rules.md` | 规则 0 分级、阈值量化到可脚本化、S 信号汇总表、数据-规则映射附录 |
| `profile.md` | 机构归属红线、观点验证记录表（✅⏳❓⚠️） |
| `views.md` | 顶部警示语、时间倒序、当前/历史分区、已过期标记、演化主线 |
| `validation.md` | 五段式验证报告、三层来源表、事件三方对照、误报归因 |
| `scripts-template/screen_template.py` | 脚本框架（非完整实现）：工具函数/参数区/五函数结构/JSON schema/三入口 |
