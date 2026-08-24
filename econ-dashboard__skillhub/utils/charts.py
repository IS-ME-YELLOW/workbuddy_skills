"""
EconDashboard - 图表工具模块
=============================
基于 Plotly 的统一图表封装，提供一致的主题配色和交互行为。
"""

import io
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── 暗色主题配色 ──────────────────────────────────────────────
BG_COLOR = "#0E1117"
CARD_BG = "#1A1D24"
TEXT_COLOR = "#E0E0E0"
GRID_COLOR = "#2E3138"
ACCENT = "#00B4D8"

# 国家配色（与 fetcher.py 一致）
COUNTRY_COLORS = {
    "China": "#E63946",
    "US": "#457B9D",
    "Japan": "#E76F51",
    "Germany": "#2A9D8F",
    "UK": "#9B5DE5",
    "India": "#F4A261",
}

DEFAULT_COLORS = [
    "#E63946", "#457B9D", "#E76F51", "#2A9D8F",
    "#9B5DE5", "#F4A261", "#00B4D8", "#FFB703",
    "#06D6A0", "#EF476F",
]


def _dark_layout(update: dict = None) -> dict:
    """返回暗色主题的基础 layout 配置。"""
    layout = {
        "template": "plotly_dark",
        "paper_bgcolor": BG_COLOR,
        "plot_bgcolor": CARD_BG,
        "font": {"color": TEXT_COLOR, "size": 12, "family": "Arial, sans-serif"},
        "xaxis": {
            "gridcolor": GRID_COLOR,
            "zerolinecolor": GRID_COLOR,
            "showgrid": True,
            "linecolor": GRID_COLOR,
        },
        "yaxis": {
            "gridcolor": GRID_COLOR,
            "zerolinecolor": GRID_COLOR,
            "showgrid": True,
            "linecolor": GRID_COLOR,
        },
        "margin": dict(l=60, r=30, t=50, b=60),
        "hovermode": "x unified",
        "legend": {
            "bgcolor": "rgba(0,0,0,0.3)",
            "bordercolor": GRID_COLOR,
            "borderwidth": 1,
        },
    }
    if update:
        layout.update(update)
    return layout


def line_chart(
    df: pd.DataFrame,
    x: str,
    y: str or list,
    title: str = "",
    xlabel: str = None,
    ylabel: str = None,
    colors: dict = None,
    markers: bool = True,
    height: int = 400,
) -> go.Figure:
    """
    绘制多线折线图。

    Parameters
    ----------
    df : pd.DataFrame
    x : str — X 轴列名
    y : str or list — Y 轴列名（单个或多个）
    title, xlabel, ylabel : str
    colors : dict — {column_name: color_hex}
    markers : bool — 是否显示标记点
    height : int
    """
    if isinstance(y, str):
        y = [y]

    fig = go.Figure()
    line_colors = colors or COUNTRY_COLORS

    for i, col in enumerate(y):
        if col not in df.columns:
            continue
        color = line_colors.get(col, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
        fig.add_trace(go.Scatter(
            x=df[x] if x in df.columns else df.index,
            y=df[col],
            mode="lines+markers" if markers else "lines",
            name=col,
            line=dict(color=color, width=2.5),
            marker=dict(size=5, color=color),
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:.2f}}<extra></extra>",
        ))

    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=16, color=TEXT_COLOR),
            x=0.5,
        ),
        xaxis_title=xlabel or x,
        yaxis_title=ylabel or "",
        height=height,
        **_dark_layout(),
    )
    return fig


def bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str or list,
    title: str = "",
    xlabel: str = None,
    ylabel: str = None,
    colors: dict = None,
    barmode: str = "group",
    height: int = 400,
) -> go.Figure:
    """
    绘制柱状图。

    Parameters
    ----------
    df : pd.DataFrame
    x : str — X 轴列名
    y : str or list — Y 轴列名
    title : str
    barmode : str — 'group' 分组, 'stack' 堆叠
    """
    if isinstance(y, str):
        y = [y]

    fig = go.Figure()
    bar_colors = colors or COUNTRY_COLORS

    for i, col in enumerate(y):
        if col not in df.columns:
            continue
        color = bar_colors.get(col, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
        fig.add_trace(go.Bar(
            x=df[x] if x in df.columns else df.index,
            y=df[col],
            name=col,
            marker_color=color,
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:.2f}}<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=TEXT_COLOR), x=0.5),
        xaxis_title=xlabel or x,
        yaxis_title=ylabel or "",
        barmode=barmode,
        height=height,
        **_dark_layout(),
    )
    return fig


def radar_chart(
    df: pd.DataFrame,
    categories: list,
    title: str = "",
    colors: dict = None,
    height: int = 500,
) -> go.Figure:
    """
    绘制雷达/蜘蛛网图，用于多维度跨国比较。

    Parameters
    ----------
    df : pd.DataFrame
        index=国家名, columns=指标类别, values=标准化数值(0-100)
    categories : list
        雷达图维度标签
    """
    fig = go.Figure()
    radar_colors = colors or COUNTRY_COLORS

    for country in df.index:
        color = radar_colors.get(country, "#FFFFFF")
        values = df.loc[country].tolist()
        # 闭合
        values_closed = values + [values[0]]
        cats_closed = list(categories) + [categories[0]]

        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=cats_closed,
            fill="toself",
            name=country,
            line=dict(color=color, width=2),
            fillcolor=f"rgba{_hex_to_rgba(color, 0.15)}",
            hovertemplate=f"<b>{country}</b><br>%{{theta}}: %{{r:.1f}}<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=TEXT_COLOR), x=0.5),
        height=height,
        polar=dict(
            bgcolor=CARD_BG,
            radialaxis=dict(
                visible=True,
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
                color=TEXT_COLOR,
            ),
            angularaxis=dict(
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
                color=TEXT_COLOR,
            ),
        ),
        **_dark_layout(),
    )
    return fig


def heatmap(
    df: pd.DataFrame,
    title: str = "",
    height: int = 450,
    colorscale: str = "RdBu_r",
) -> go.Figure:
    """
    绘制相关性热力图。

    Parameters
    ----------
    df : pd.DataFrame — 相关性矩阵
    title : str
    """
    fig = go.Figure(data=go.Heatmap(
        z=df.values,
        x=df.columns,
        y=df.index,
        colorscale=colorscale,
        zmid=0,
        text=np.round(df.values, 2),
        texttemplate="%{text}",
        textfont=dict(size=10, color=TEXT_COLOR),
        hovertemplate="%{x} vs %{y}<br>相关系数: %{z:.3f}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=TEXT_COLOR), x=0.5),
        height=height,
        xaxis=dict(tickangle=45, gridcolor=GRID_COLOR),
        yaxis=dict(gridcolor=GRID_COLOR),
        **_dark_layout(),
    )
    return fig


def scatter_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color_col: str = None,
    size_col: str = None,
    title: str = "",
    xlabel: str = None,
    ylabel: str = None,
    height: int = 450,
) -> go.Figure:
    """
    散点图，可带颜色/尺寸维度。
    """
    if color_col:
        fig = px.scatter(
            df, x=x, y=y, color=color_col, size=size_col,
            title=title,
            color_discrete_map=COUNTRY_COLORS,
        )
        fig.update_traces(
            marker=dict(line=dict(width=1, color="white")),
            hovertemplate="<br>".join([
                f"<b>%{{customdata[0]}}</b>",
                f"{x}: %{{x:.2f}}",
                f"{y}: %{{y:.2f}}",
                "<extra></extra>",
            ]),
        )
        fig.update_traces(
            customdata=df[[color_col]].values if color_col in df.columns else None
        )
    else:
        fig = px.scatter(
            df, x=x, y=y, title=title,
        )

    fig.update_layout(
        height=height,
        xaxis_title=xlabel or x,
        yaxis_title=ylabel or y,
        **_dark_layout(),
    )
    # 保证 hover 可见
    fig.update_traces(
        hovertemplate=f"<b>%{{text}}</b><br>{x}: %{{x:.2f}}<br>{y}: %{{y:.2f}}<extra></extra>",
        text=df.index if color_col is None else df[color_col],
    )
    return fig


def metric_card(value, label, delta=None, prefix="", suffix=""):
    """
    返回一个 Plotly 指标卡片（通过 HTML + Streamlit 渲染）。

    注意: 这个函数返回字符串用于 st.markdown + HTML，不是 Figure。
    """
    delta_str = ""
    if delta is not None:
        arrow = "&#9650;" if delta >= 0 else "&#9660;"
        delta_color = "#06D6A0" if delta >= 0 else "#EF476F"
        delta_str = (
            f'<span style="font-size:14px; color:{delta_color}; margin-left:8px;">'
            f'{arrow} {abs(delta):.1f}%</span>'
        )

    return f"""
    <div style="
        background-color: {CARD_BG};
        border-radius: 12px;
        padding: 20px;
        border: 1px solid {GRID_COLOR};
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    ">
        <div style="font-size: 28px; font-weight: 700; color: {ACCENT};">
            {prefix}{value:,}{suffix}
        </div>
        <div style="font-size: 14px; color: {TEXT_COLOR}; margin-top: 6px;">
            {label}{delta_str}
        </div>
    </div>
    """


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> tuple:
    """将 hex 颜色转为 rgba 元组。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}, {alpha}"
