# EconDashboard — 交互式经济数据看板

> 实时宏观经济数据可视化平台，覆盖中美日德英印6大经济体，支持 20+ 指标的交互式分析。

---

## Features

- **多源数据聚合** — 自动从 World Bank、FRED（美联储）、akshare（中国国家统计局）采集数据，无需任何 API Key
- **中国经济高频跟踪** — CPI、PPI、PMI、工业增加值、固定资产投资、零售、贸易、M2、社融等高频指标一览
- **跨国比较** — 雷达图、散点图、相关性矩阵，一键对比 6 大经济体的健康度
- **一键导出 CSV** — 所有数据表格支持下载为 CSV 文件
- **交互式可视化** — 基于 Plotly 的缩放、悬停、筛选全功能图表

## Quick Start

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动应用
streamlit run app.py
```

> 首次启动时，由于数据取数需要从各 API 获取，请确保网络通畅。

## 目录结构

```
econ-dashboard/
├── README.md
├── requirements.txt
├── app.py                          # 主应用入口
├── data/
│   └── fetcher.py                  # 数据获取层（World Bank / FRED / akshare）
├── pages/
│   ├── 01_macro_overview.py        # 宏观概览
│   ├── 02_china_tracker.py         # 中国经济高频跟踪
│   └── 03_comparison.py            # 跨国比较
└── utils/
    └── charts.py                   # 图表工具（Plotly 封装）
```

## 数据来源

| 数据源 | 覆盖范围 | 认证方式 |
|--------|----------|----------|
| [World Bank API](https://api.worldbank.org/v2/) | GDP、GDP 增长率、CPI | 无需 Key |
| [FRED (Federal Reserve)](https://fred.stlouisfed.org/) | 美国失业率、CPI、利率 | 无需 Key（pandas-datareader） |
| [akshare](https://www.akshare.xyz/) | 中国宏观经济全系列数据 | 无需 Key |

## 技术栈

- **Python 3.9+**
- **Streamlit** — 快速构建数据应用
- **Plotly** — 交互式图表
- **pandas / numpy** — 数据处理
- **pandas-datareader** — FRED 数据接口
- **akshare** — 中国金融数据接口

## 适用场景

- **产业研究** — 快速了解目标经济体宏观环境
- **宏观分析** — 跟踪 GDP / CPI / PMI 趋势变化
- **投前调研** — 跨国比较辅助投资决策

## License

MIT
