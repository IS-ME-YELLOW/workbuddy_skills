"""
跨国比较页面
=============
- 多国 5+ 指标对比
- 雷达图: 经济健康度综合评价
- 相关性矩阵: 各指标之间的相关性
- 散点图: GDP vs CPI, GDP vs 失业率
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

# 国家列表
COUNTRIES = ["China", "US", "Japan", "Germany", "UK", "India"]

# 国家配色
COUNTRY_COLORS = {
    "China": "#E63946",
    "US": "#457B9D",
    "Japan": "#E76F51",
    "Germany": "#2A9D8F",
    "UK": "#9B5DE5",
    "India": "#F4A261",
}


def render():
    st.markdown(
        "<h1 style='font-size: 28px;'>🌍 跨国经济比较</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #9CA3AF; font-size: 14px;'>"
        "6 大经济体多维指标对比分析</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 年份选择 ──
    current_year = datetime.now().year
    selected_year = st.selectbox(
        "选择比较基准年份",
        options=list(range(current_year, current_year - 5, -1)),
        index=0,
    )

    # ── 加载数据 ──
    with st.spinner(f"正在加载 {selected_year} 年数据..."):
        gdp_data = _load_gdp(15)
        cpi_data = _load_cpi(15)
        us_unemp = _load_fred("UNRATE")
        china_pmi = _load_pmi()

    # ── 第1行: 雷达图（综合经济健康度） ──
    st.markdown(
        "<h3 style='font-size: 20px;'>🎯 经济健康度雷达图</h3>",
        unsafe_allow_html=True,
    )

    radar_df = _build_radar_data(
        gdp_data, cpi_data, us_unemp, china_pmi, selected_year
    )

    if radar_df is not None and not radar_df.empty:
        categories = radar_df.columns.tolist()
        fig = _radar_chart(radar_df, categories, "经济健康度综合评分 (0-100)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("数据不足，无法绘制雷达图。")

    # ── 第2行: 详细指标对比表格 ──
    st.divider()
    st.markdown(
        "<h3 style='font-size: 20px;'>📋 各指标详细数值</h3>",
        unsafe_allow_html=True,
    )

    compare_df = _build_comparison_df(
        gdp_data, cpi_data, us_unemp, china_pmi, selected_year
    )
    if compare_df is not None and not compare_df.empty:
        st.dataframe(compare_df, use_container_width=True)

        csv = compare_df.to_csv(encoding="utf-8-sig")
        st.download_button(
            label="📥 下载比较数据 CSV",
            data=csv,
            file_name=f"comparison_{selected_year}.csv",
            mime="text/csv",
        )
    else:
        st.info("比较数据暂不可用。")

    # ── 第3行: 散点图 ──
    st.divider()
    st.markdown(
        "<h3 style='font-size: 20px;'>📊 指标关联散点图</h3>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        scatter_df = _build_scatter_data(gdp_data, cpi_data, selected_year, "CPI")
        if scatter_df is not None and not scatter_df.empty:
            fig = _scatter_chart(
                scatter_df,
                x="GDP_growth",
                y="CPI",
                color_col="country",
                title=f"{selected_year} 年 GDP 增长 vs CPI 通胀",
                xlabel="GDP 增长率 (%)",
                ylabel="CPI 通胀率 (%)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("GDP vs CPI 数据暂不可用。")

    with col2:
        scatter_df2 = _build_scatter_data(
            gdp_data, cpi_data, selected_year, "unemp"
        )
        if scatter_df2 is not None and not scatter_df2.empty:
            fig = _scatter_chart(
                scatter_df2,
                x="GDP_growth",
                y="unemployment",
                color_col="country",
                title=f"{selected_year} 年 GDP 增长 vs 失业率",
                xlabel="GDP 增长率 (%)",
                ylabel="失业率 (%)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("GDP vs 失业率数据暂不可用。")

    # ── 第4行: 相关性矩阵 ──
    st.divider()
    st.markdown(
        "<h3 style='font-size: 20px;'>🔗 指标相关性矩阵 (近5年)</h3>",
        unsafe_allow_html=True,
    )

    corr_df = _build_correlation_data(gdp_data, cpi_data, 5)
    if corr_df is not None and not corr_df.empty:
        fig = _heatmap_chart(corr_df, "指标相关性矩阵 (Pearson)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("相关性分析数据暂不可用，需要连续5年以上的数据。")

    # ── 数据说明 ──
    st.divider()
    st.markdown(
        "<div style='font-size: 12px; color: #6B7280;'>"
        "数据说明:<br>"
        "- GDP 增长率: World Bank (NY.GDP.MKTP.KD.ZG) — 不变价年增长率 %<br>"
        "- CPI 通胀率: World Bank (FP.CPI.TOTL.ZG) — 消费者价格年变化率 %<br>"
        "- 失业率: FRED (UNRATE) — 仅美国数据可用<br>"
        "- PMI: akshare (中国制造业 PMI)<br>"
        "- 雷达图评分基于各指标在 6 国中的相对排名标准化 (0-100)"
        "</div>",
        unsafe_allow_html=True,
    )


# ═════════════════════════════════════════════════════════════
#  数据加载
# ═════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def _load_gdp(years=15):
    from data.fetcher import fetch_gdp_data
    return fetch_gdp_data(years=years)


@st.cache_data(ttl=3600)
def _load_cpi(years=15):
    from data.fetcher import fetch_cpi_data
    return fetch_cpi_data(years=years)


@st.cache_data(ttl=3600)
def _load_fred(series_id):
    from data.fetcher import fetch_fred_series
    return fetch_fred_series(series_id)


@st.cache_data(ttl=1800)
def _load_pmi():
    from data.fetcher import fetch_pmi_data
    return fetch_pmi_data()


# ═════════════════════════════════════════════════════════════
#  雷达图数据构建
# ═════════════════════════════════════════════════════════════

def _build_radar_data(
    gdp_data: dict,
    cpi_data: pd.DataFrame,
    us_unemp: pd.Series,
    china_pmi: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """
    构建雷达图所需数据。
    每个指标做 0-100 标准化（越大越好）：
    - GDP 增长率: 越高越好
    - CPI 通胀: 2% 为最优，偏离越远越差
    - 失业率: 越低越好 (仅美国可用)
    - PMI: 50 以上越高的越好 (仅中国可用)
    """
    gdp_growth = gdp_data.get("gdp_growth", pd.DataFrame())
    if gdp_growth.empty:
        return None

    # 获取指定年份各国家的数据
    available = [c for c in gdp_growth.columns if c in COUNTRIES]

    if year not in gdp_growth.index:
        # 使用最新的可用年份
        available_years = gdp_growth.index[gdp_growth.index <= year]
        if len(available_years) == 0:
            return None
        year = available_years.max()

    scores = {}

    for country in available:
        vals = {}

        # 1. GDP 增长率 (越高的越好)
        g = gdp_growth.loc[year, country] if country in gdp_growth.columns else np.nan
        vals["GDP 增长率"] = g if pd.notna(g) else np.nan

        # 2. CPI 通胀 (2% 为最优)
        cpi_val = cpi_data.loc[year, country] if (
            not cpi_data.empty and country in cpi_data.columns
            and year in cpi_data.index
        ) else np.nan
        if pd.notna(cpi_val):
            vals["CPI 温和度"] = cpi_val
        else:
            vals["CPI 温和度"] = np.nan

        # 3. 失业率 (仅美国, 越低越好)
        if country == "US" and not us_unemp.empty:
            # 取最近的值
            latest_unemp = us_unemp.dropna()
            if not latest_unemp.empty:
                vals["失业率"] = latest_unemp.iloc[-1]
            else:
                vals["失业率"] = np.nan

        # 4. PMI (仅中国, 50以上越高越好)
        if country == "China" and not china_pmi.empty:
            pmi_cols = [c for c in china_pmi.columns if "PMI" in str(c) or "制造业" in str(c)]
            if pmi_cols:
                pmi_vals = china_pmi[pmi_cols[0]].dropna()
                if not pmi_vals.empty:
                    vals["PMI"] = pmi_vals.iloc[-1]

        # 5. GDP 总量 (越高越好)
        gdp_usd = gdp_data.get("gdp_usd", pd.DataFrame())
        if not gdp_usd.empty and country in gdp_usd.columns and year in gdp_usd.index:
            vals["经济规模"] = gdp_usd.loc[year, country]

        scores[country] = vals

    if not scores:
        return None

    # 构建 DataFrame
    df = pd.DataFrame(scores).T
    df = df.dropna(axis=1, how="all")

    if df.empty or df.shape[1] < 3:
        return None

    # 标准化每个维度到 0-100
    for col in df.columns:
        if col == "CPI 温和度":
            # CPI: 2% 最优，偏离越远越差
            optimal = 2.0
            df[col] = df[col].apply(lambda x: max(0, 100 - abs(x - optimal) * 25) if pd.notna(x) else np.nan)
        elif col == "失业率":
            # 失业率越低越好 (取反)
            if df[col].notna().sum() > 0:
                max_val = df[col].max()
                min_val = df[col].min()
                if max_val > min_val:
                    df[col] = (max_val - df[col]) / (max_val - min_val) * 100
                else:
                    df[col] = 50
        else:
            # 越大越好的指标：min-max 标准化
            if df[col].notna().sum() > 0:
                max_val = df[col].max()
                min_val = df[col].min()
                if max_val > min_val:
                    df[col] = (df[col] - min_val) / (max_val - min_val) * 100
                else:
                    df[col] = 50

    # 仅保留有数据的国家
    df = df.dropna(how="all")
    # 仅保留有足够数据的列
    df = df.dropna(axis=1, thresh=max(1, int(len(df) * 0.5)))

    return df.round(0).astype(int) if not df.empty else None


# ═════════════════════════════════════════════════════════════
#  详细指标对比表
# ═════════════════════════════════════════════════════════════

def _build_comparison_df(
    gdp_data: dict,
    cpi_data: pd.DataFrame,
    us_unemp: pd.Series,
    china_pmi: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """构建各国家多指标对比 DataFrame。"""
    gdp_growth = gdp_data.get("gdp_growth", pd.DataFrame())
    gdp_usd = gdp_data.get("gdp_usd", pd.DataFrame())

    rows = []
    for country in COUNTRIES:
        row = {"国家": country}

        # GDP 增长率
        if not gdp_growth.empty and country in gdp_growth.columns and year in gdp_growth.index:
            val = gdp_growth.loc[year, country]
            row["GDP 增长率 (%)"] = round(val, 2) if pd.notna(val) else None

        # GDP 总量
        if not gdp_usd.empty and country in gdp_usd.columns and year in gdp_usd.index:
            val = gdp_usd.loc[year, country]
            row["GDP (亿美元)"] = round(val, 0) if pd.notna(val) else None

        # CPI
        if not cpi_data.empty and country in cpi_data.columns and year in cpi_data.index:
            val = cpi_data.loc[year, country]
            row["CPI 通胀率 (%)"] = round(val, 2) if pd.notna(val) else None

        # 失业率
        if country == "US" and not us_unemp.empty:
            latest = us_unemp.dropna()
            if not latest.empty:
                row["失业率 (%)"] = round(latest.iloc[-1], 1)

        # PMI
        if country == "China" and not china_pmi.empty:
            pmi_cols = [c for c in china_pmi.columns if "PMI" in str(c) or "制造业" in str(c)]
            if pmi_cols:
                vals = china_pmi[pmi_cols[0]].dropna()
                if not vals.empty:
                    row["制造业 PMI"] = round(vals.iloc[-1], 1)

        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.set_index("国家")
    return df


# ═════════════════════════════════════════════════════════════
#  散点图数据
# ═════════════════════════════════════════════════════════════

def _build_scatter_data(
    gdp_data: dict,
    cpi_data: pd.DataFrame,
    year: int,
    secondary: str,
) -> pd.DataFrame:
    """
    构建散点图数据。
    secondary: 'CPI' 或 'unemp'
    """
    gdp_growth = gdp_data.get("gdp_growth", pd.DataFrame())
    if gdp_growth.empty or year not in gdp_growth.index:
        return None

    rows = []
    for country in COUNTRIES:
        row = {"country": country}

        # GDP 增长率
        if country in gdp_growth.columns:
            val = gdp_growth.loc[year, country]
            row["GDP_growth"] = val if pd.notna(val) else None
        else:
            continue

        if secondary == "CPI":
            if not cpi_data.empty and country in cpi_data.columns and year in cpi_data.index:
                val = cpi_data.loc[year, country]
                row["CPI"] = val if pd.notna(val) else None
            else:
                row["CPI"] = None
        elif secondary == "unemp":
            if country == "US":
                from data.fetcher import fetch_fred_series
                unemp = fetch_fred_series("UNRATE")
                if not unemp.empty:
                    row["unemployment"] = round(unemp.iloc[-1], 1)
                else:
                    row["unemployment"] = None
            else:
                row["unemployment"] = None

        rows.append(row)

    df = pd.DataFrame(rows).dropna()
    return df if not df.empty else None


# ═════════════════════════════════════════════════════════════
#  相关性矩阵
# ═════════════════════════════════════════════════════════════

def _build_correlation_data(
    gdp_data: dict,
    cpi_data: pd.DataFrame,
    years: int = 5,
) -> pd.DataFrame:
    """
    构建各指标间的相关性矩阵。

    使用近 N 年的数据，将所有国家的数据合并计算指标间的相关性。
    """
    gdp_growth = gdp_data.get("gdp_growth", pd.DataFrame())
    gdp_usd = gdp_data.get("gdp_usd", pd.DataFrame())

    if gdp_growth.empty or cpi_data.empty:
        return None

    # 找到共同年份
    common_years = sorted(
        set(gdp_growth.index) & set(cpi_data.index)
    )[-years:]

    if len(common_years) < 3:
        return None

    rows = []
    for year in common_years:
        for country in COUNTRIES:
            if (country in gdp_growth.columns and country in cpi_data.columns):
                g = gdp_growth.loc[year, country]
                c = cpi_data.loc[year, country]
                u = (gdp_usd.loc[year, country]
                     if not gdp_usd.empty and country in gdp_usd.columns
                     else None)
                if pd.notna(g) and pd.notna(c):
                    rows.append({
                        "GDP_增长": g,
                        "CPI_通胀": c,
                        "GDP_总量": u if pd.notna(u) else np.nan,
                    })

    if len(rows) < 5:
        return None

    df = pd.DataFrame(rows).dropna(how="any")
    if df.shape[0] < 5 or df.shape[1] < 2:
        return None

    corr = df.corr(method="pearson")
    return corr


# ═════════════════════════════════════════════════════════════
#  图表包装
# ═════════════════════════════════════════════════════════════

def _radar_chart(df, categories, title):
    from utils.charts import radar_chart as rc
    return rc(df, categories, title=title, height=550)


def _scatter_chart(df, x, y, color_col, title, xlabel, ylabel):
    from utils.charts import scatter_chart as sc
    return sc(df, x, y, color_col=color_col, title=title,
              xlabel=xlabel, ylabel=ylabel, height=400)


def _heatmap_chart(df, title):
    from utils.charts import heatmap as hm
    return hm(df, title=title, height=400)


if __name__ == "__main__":
    render()
