我看了这个 repo 里几个代表性的 Skill，包括 `analyst-macro-guolei`、`analyst-macro-lichao`、`analyst-macro-zhangyu`、`analyst-strategy-zhangyidong`。结论比较明确：

> **问题不只是“SKILL.md 太长”，而是 Progressive Disclosure（渐进加载）基本失效了。**
>
> 当前结构虽然形式上用了 `SKILL.md + references + assets + scripts`，但运行逻辑实际上会诱导模型把整套知识库读进上下文。

这正好违反 Agent Skills 的设计思想：metadata 常驻应很小，`SKILL.md` 激活后加载，references 应该**按需读取**，脚本应该尽量**直接执行而不是读源码**。Microsoft 的 Agent Skills 文档也明确建议激活后的 Skill 控制在约 5000 tokens 内，并按需读资源、运行脚本；Anthropic 的 skill-creator 同样强调 references 应按需读取而不是整体加载。([Microsoft Learn][1])

## 1. 当前最严重的问题：一次任务形成“全量加载链”

以 `analyst-macro-lichao` 为例：

| 文件                  |          大小 |
| ------------------- | ----------: |
| `SKILL.md`          |     7.99 KB |
| `views.md`          |     5.59 KB |
| `framework.md`      |     16.7 KB |
| `decision-rules.md` |     16.2 KB |
| `indicators.md`     |     8.16 KB |
| `screen.py`         |     29.2 KB |
| **合计**              | **约 84 KB** |

([GitHub][2])

`SKILL.md` 自己只有 8 KB，其实并没有特别夸张。

真正的问题是它写了：

> 1. 先读 views
> 2. 调 framework
> 3. 跑 screen.py
> 4. 使用 decision-rules
> 5. 查 indicators
> 6. 再回 views 做配置

也就是说，一旦 agent 严格执行“按顺序执行”，一个普通问题都有机会变成：

```text
SKILL
 ↓
views
 ↓
framework
 ↓
indicators
 ↓
decision-rules
 ↓
screen.py/schema
 ↓
用户数据
 ↓
回答
```

这实际上不是 Progressive Disclosure，而是：

```text
Progressive Full Disclosure
```

更明显的是，下面明明又有一个“触发场景速查”：

```text
黄金怎么看？
→ 央行购金框架 → S7/S8

红利股还能配吗？
→ 股息率-票息比价 → S5
```

但顶部同时要求“按顺序执行全流程”。这两个指令实际上存在冲突。([GitHub][2])

### 应该改成

```text
默认：只处理与用户问题直接相关的路径。

只有用户明确问：
- 当前完整宏观环境
- 全资产配置
- 完整月度策略

才运行 full workflow。
```

这是第一优先级改动。

---

# 2. `description` 严重过载

这是第二个我认为非常重要的问题。

例如李超 Skill 的 description 几乎变成了一篇“小型知识摘要”：

* 四层次框架
* 中美 GDP
* 10Y 国债
* 科技红利
* 存款搬家
* K 型经济
* 新黄金
* 出口
* 黄金
* 平准基金
* 50/50
* 一堆报告标题
* 一堆 trigger keyword

([GitHub][2])

张忆东、张瑜也是同样模式。([GitHub][3])

这件事情的严重程度很容易被低估。

因为 **Skill description 属于第一级 metadata，通常是在 Skill 尚未激活之前就参与路由的。**

官方 Agent Skills 的 progressive disclosure 设计就是：

```text
Level 1
name + description
≈ 100 tokens / skill

Level 2
SKILL.md

Level 3
references

Level 4
scripts
```

([Microsoft Learn][1])

如果以后你有：

```text
郭磊
李超
张瑜
张忆东
...
20 个分析师
50 个分析师
100 个分析师
```

每个人 description 都写 300–500 tokens，那么**光 Skill router 自己就已经产生 context pollution**。

### 现在这种

```yaml
description: 李超……四层次……GDP……10Y……K型……
新黄金……存款搬家……央行购金……5600美元……
平准基金……50%黄金……
```

### 建议变成

```yaml
description: >
  使用李超（浙商证券）的宏观与资产配置框架分析中国市场。
  当用户明确询问李超观点，或需要用其“中美博弈—流动性—
  科技/红利杠铃”框架进行市场判断时使用。
```

大约缩掉 **70–85%**。

具体概念不要用于 metadata 枚举。

---

# 3. `framework.md` 的粒度太粗

现在：

```text
references/
├── framework.md         16.7 KB
├── decision-rules.md    16.2 KB
└── indicators.md         8.2 KB
```

这在文件管理角度很整齐。

但是在 **LLM context management** 角度并不好。

因为用户问：

> 黄金怎么看？

实际上只需要：

```text
黄金框架
+
黄金指标
+
黄金规则
+
当前观点
```

但现在模型要么读整个 `framework.md`，要么需要在一个 16KB 文件里定位 framework 11。

Agent Skills 官方建议的思路反而是：

> reference 文件保持 focused，越小越容易按需加载。([Claude][4])

---

# 4. 我更推荐“按任务切片”，而不是“按文档类型切片”

你现在是：

```text
references/
├── framework.md
├── indicators.md
└── decision-rules.md
```

这是**人类写研究报告的组织方式**。

但 Skill 更适合：

```text
references/
├── router.md
└── playbooks/
    ├── regime.md
    ├── liquidity.md
    ├── tech-vs-dividend.md
    ├── deposit-migration.md
    ├── gold.md
    ├── policy.md
    └── stock-selection.md
```

例如：

### `gold.md`

只包含：

```text
Framework
央行购金框架

Indicators
央行购金
金价
实际利率
美元

Rules
四大利空
趋势确认

Current view
只在必要时读取最新观点
```

这样：

```text
用户：黄金怎么看？

SKILL.md
   ↓
router 判断 gold
   ↓
playbooks/gold.md
   ↓
获取 3~4 个最新数据
   ↓
回答
```

可能只需要 **2–5 KB 的 Skill context**。

而不是 50KB。

---

# 5. 最大的结构改进：把 Rule / Indicator / Script 做成 Single Source of Truth

当前还有一个明显的工程问题：

同一个东西重复存在于三个位置。

比如：

```text
10Y 国债
1.5%-2%
中枢 1.75%
```

同时存在于：

```text
framework.md
indicators.md
decision-rules.md
screen.py
SKILL.md
```

相关内容在当前 repo 里确实多次重复。([GitHub][5])

这会产生两个问题：

### Context duplication

LLM 连续看到：

```text
1.5-2
1.75
1.5-2
1.75
1.5-2
1.75
```

没有增加多少信息，却消耗上下文。

### Drift

未来分析师更新：

```text
1.5%-2%
↓
1.4%-1.9%
```

你可能只改了：

```text
framework.md
```

却没改：

```text
screen.py
decision-rules.md
indicators.md
```

于是 Skill 自己出现冲突。

---

# 6. 建议把参数全部结构化

例如：

```text
config/
├── signals.yaml
├── indicators.yaml
└── sources.yaml
```

例如：

```yaml
S3:
  name: rate_regime
  inputs:
    - cn_10y

  thresholds:
    lower: 1.5
    center: 1.75
    upper: 2.0

  provenance:
    type: analyst_original
    confidence: high

  framework:
    tech_weight: positive_when_rate_falling
```

然后：

```text
screen.py
       ↓
读取 signals.yaml
```

而不是在 Python 里面重新 hardcode 一遍。

Markdown 只解释：

> 为什么这个 signal 有意义。

这样就形成：

```text
YAML = truth
Python = calculation
Markdown = interpretation
```

这是比当前结构稳健很多的设计。

---

# 7. `screen.py` 29KB 本身不算问题，但不要让模型读它

这是个非常关键的区别。

**脚本长没有问题。**

Agent Skills 的设计允许 scripts 很大，因为本意就是：

> run script，而不是把 script 塞进 LLM context。([Microsoft Learn][1])

现在的问题是 `SKILL.md` 写：

> schema 见脚本头部说明。

这就很危险。

因为 agent 为了知道怎么调用脚本，很可能：

```text
read scripts/screen.py
```

然后 580 行直接进入上下文。该脚本目前确实约 29.2KB。([GitHub][6])

### 应该变成

```text
scripts/
├── screen.py
└── schema.json
```

或者让：

```bash
python scripts/screen.py --schema
```

返回：

```json
{
  "required": ["cn_10y", "dividend_yield"],
  "optional": ["dr001"]
}
```

Skill 只写：

```text
DO NOT read screen.py.

To obtain its input contract:
python scripts/screen.py --schema

To calculate:
python scripts/screen.py --scenario gold --data input.json
```

我甚至建议把这句话明确写进去：

```text
Never read scripts/screen.py unless debugging the script itself.
Execute it directly.
```

这一项就可能直接省掉 **~30KB context**。

---

# 8. `assets/` 现在语义也有点错

目前：

```text
assets/
├── profile.md
├── validation.md
└── views.md
```

但这三个其实都不是典型 asset。

通常 `assets` 更适合：

```text
模板
图片
输出文件
静态资源
```

Anthropic 的 skill anatomy 也是这样定义：scripts 放可执行代码，references 放文档，assets 放输出所需文件。([GitHub][7])

所以建议：

```text
references/
├── analyst-profile.md
├── current-views.md
└── ...
```

而：

```text
validation.md
```

甚至不应该在 production runtime Skill 里面。

移到：

```text
evals/
validation/
tests/
```

即可。

用户正常问：

> 李超怎么看科技？

完全没有理由让 agent 看回测报告。

---

# 9. 当前还有一个比长度更严重的逻辑问题

当前很多 Skill 写着：

> **信号与观点冲突时优先遵循信号。**

例如李超 Skill 就明确这样规定。([GitHub][2])

但是同一个 Skill 又说明很多 signal threshold 是：

```text
❌ 推断
```

例如中美事件：

```text
强对抗 -2
一般对抗 -1
一般合作 +1
强合作 +2
近 3 个月窗口
```

都是人为工程化规则，不是李超本人给出的量化体系。([GitHub][8])

那么：

```text
工程师自己造的 signal
>
分析师本人观点
```

逻辑上是不成立的。

这可能导致一种很危险的输出：

```text
李超认为科技应该减仓
```

实际上是：

```text
你的程序按照人为设计的 -2/-1/+1/+2
推导出科技应该减仓
```

两者完全不是一回事。

### 应改为三级 provenance

```text
A: analyst_original
分析师明确说过

B: derived
依据分析师公式计算

C: engineered
为了 Skill 可执行性人为构造
```

冲突时：

```text
A > B > C
```

而不是：

```text
signal > analyst
```

输出中：

```text
分析师观点：
...

框架推导：
...

工程化 signal：
...
```

三个层次明确区分。

这会让整个 Skill 的可信度明显提高。

---

# 10. 我建议最终重构成这个结构

对于**单分析师 Skill**：

```text
analyst-macro-lichao/
│
├── SKILL.md                  # 1~2 KB，只做路由
│
├── references/
│   ├── index.md              # 框架地图，<1 KB
│   │
│   ├── playbooks/
│   │   ├── market-regime.md
│   │   ├── liquidity.md
│   │   ├── tech-dividend.md
│   │   ├── deposit-migration.md
│   │   ├── gold.md
│   │   └── policy.md
│   │
│   ├── current-view.md
│   ├── provenance.md
│   └── sources.md
│
├── config/
│   ├── indicators.yaml
│   └── signals.yaml
│
└── scripts/
    └── screen.py
```

然后 Skill 的运行图变成：

```text
                 user query
                     │
                     ▼
                 SKILL.md
                     │
              intent routing
             ┌───────┼───────┐
             ▼       ▼       ▼
           gold   liquidity  style
             │       │       │
             └───────┼───────┘
                     ▼
              one playbook.md
                     │
                     ▼
               fetch data
                     │
             need calculation?
                │         │
               yes        no
                │         │
                ▼         │
             screen.py    │
                │         │
                └────┬────┘
                     ▼
                   answer
```

这才是真正的 Progressive Disclosure。

---

# 11. `SKILL.md` 本身可以缩成这个级别

比如李超版本，我会缩成类似：

```markdown
---
name: analyst-macro-lichao
description: >
  使用李超（浙商证券）的宏观及资产配置框架分析中国市场。
  当用户明确询问李超观点，或希望使用中美博弈、流动性、
  科技/红利杠铃框架判断市场时使用。
---

# 李超宏观框架

使用李超的方法论分析市场。
区分：
- analyst_original：分析师明确观点
- derived：根据分析师框架计算
- engineered：本 Skill 工程化规则

不得把 derived / engineered 表述为分析师本人观点。

## Route

根据问题只读取一个主要 playbook：

| Intent | Resource |
|---|---|
| 当前完整市场环境 | `playbooks/market-regime.md` |
| 科技 vs 红利 | `playbooks/tech-dividend.md` |
| 流动性 / 股债双牛 | `playbooks/liquidity.md` |
| 存款搬家 | `playbooks/deposit-migration.md` |
| 黄金 | `playbooks/gold.md` |
| 政策 | `playbooks/policy.md` |
| 李超最新观点 | `current-view.md` |

默认不要运行完整流程。

只有用户明确要求完整市场诊断或资产配置时，
才组合多个 playbook。

## Calculation

需要量化信号时运行：

python scripts/screen.py --scenario <scenario> --data <file>

不要读取 `screen.py` 源码。
输入格式通过：

python scripts/screen.py --schema <scenario>

获取。

## Freshness

涉及“当前 / 最新 / 现在”：
先确认数据与观点的 as_of。
过期则获取最新信息，不得直接把历史快照作为当前观点。

## Output

依次给出：

1. 结论
2. 当前证据
3. 李超原始框架
4. 框架推导
5. 不确定性 / engineered assumptions
```

实际上就够了。

这比现在的 8KB 入口还可以再缩 **约 60–75%**。

---

# 12. 如果未来要做到几十/上百个分析师，我甚至不建议“一人一个 Skill”

你现在：

```text
analyst-macro-guolei
analyst-macro-lichao
analyst-macro-zhangyu
analyst-strategy-zhangyidong
...
```

4 个问题还不明显。

到了 50 个以后：

```text
50 × description metadata
```

就会成为新的 context pollution。

我会进一步变成：

```text
analyst-research/
│
├── SKILL.md
│
├── references/
│   ├── analysts-index.md
│   │
│   ├── guolei/
│   │   ├── index.md
│   │   └── playbooks/...
│   │
│   ├── lichao/
│   │   ├── index.md
│   │   └── playbooks/...
│   │
│   ├── zhangyu/
│   └── zhangyidong/
│
├── config/
│   ├── guolei.yaml
│   ├── lichao.yaml
│   ├── zhangyu.yaml
│   └── zhangyidong.yaml
│
└── scripts/
    └── screen.py
```

第一级只广告：

```text
analyst-research
```

用户说：

> 用张瑜框架看现在 A 股

才：

```text
analyst-research
→ analyst index
→ zhangyu/index
→ 对应 playbook
```

如果你准备继续大规模收集券商分析师，我认为这会比“一分析师一个 Skill”更合理。

---

## 我的优先级建议

你现在不用大规模推倒重来，先做四件事：

| 优先级    | 改动                                                    | 效果                    |
| ------ | ----------------------------------------------------- | --------------------- |
| **P0** | 删除“默认按顺序执行全流程”，改为 intent routing                      | 最大幅减少 context         |
| **P0** | 禁止读取 `screen.py`，增加 `--schema`                        | 单次最多少约 29KB           |
| **P1** | 将 framework/rules/indicators 改成按 scenario 的 playbooks | 单任务从几十 KB 降至几 KB      |
| **P1** | `description` 缩到约 100 tokens                          | 防止多 Skill metadata 污染 |
| P2     | YAML 做 signal single source of truth                  | 防重复、防 drift           |
| P2     | provenance 改成 original/derived/engineered             | 提升可信度                 |
| P3     | validation/cases 移出 production skill                  | 减少诱导加载                |

所以我不会简单地说“把 SKILL.md 从 67 行砍到 30 行”。

**真正应该改的是加载拓扑。**

当前：

```text
一个 Skill
→ 一套完整知识库
→ 全部加载
→ 做一个问题
```

应该变成：

```text
一个 Skill
→ router
→ 一个 2~4KB playbook
→ 必要的数据
→ deterministic script
→ answer
```

这才是解决“模型无法处理”的根本方法。官方 Skill 指南本身强调的也是这种 progressive disclosure，而不是单纯追求文件数量少。([Microsoft Learn][1])

如果按你这个项目继续做，我会优先选择 **“一个 analyst-research router Skill + 多个分析师 knowledge packs + scenario playbooks + 通用 screen engine”**，而不是继续复制现在这种 `framework.md + indicators.md + decision-rules.md + screen.py` 四件套。这样扩展到几十个分析师时也不会迅速把模型上下文撑爆。
