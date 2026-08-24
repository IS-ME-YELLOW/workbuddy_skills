"""
EconDashboard - 数据获取模块
================================
使用免费公共 API（无需 API Key）获取宏观经济数据。
数据源: World Bank API, FRED (pandas-datareader), akshare (中国数据)
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── 国家代码映射 ──────────────────────────────────────────────
COUNTRY_CODES = {
    "China": "CN",
    "US": "US",
    "Japan": "JP",
    "Germany": "DE",
    "UK": "GB",
    "India": "IN",
}

COUNTRY_ISO3 = {
    "China": "CHN",
    "US": "USA",
    "Japan": "JPN",
    "Germany": "DEU",
    "UK": "GBR",
    "India": "IND",
}

# ── 国家配色（与 charts.py 保持一致） ────────────────────────
COUNTRY_COLORS = {
    "China": "#E63946",
    "US": "#457B9D",
    "Japan": "#E76F51",
    "Germany": "#2A9D8F",
    "UK": "#9B5DE5",
    "India": "#F4A261",
}


# ═════════════════════════════════════════════════════════════
#  World Bank API 工具函数
# ═════════════════════════════════════════════════════════════

def _wb_fetch_indicator(
    country_iso3: str,
    indicator: str,
    date_start: int = 2015,
    date_end: int = None,
    max_retries: int = 3,
) -> pd.Series:
    """
    从 World Bank API 获取单个国家/单个指标的时间序列。
    返回 index=年份, values=数值 的 Series。
    """
    if date_end is None:
        date_end = datetime.now().year

    url = (
        f"https://api.worldbank.org/v2/country/{country_iso3}/"
        f"indicator/{indicator}"
        f"?format=json&date={date_start}:{date_end}&per_page=500"
    )

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) > 1 and data[1] is not None:
                    records = data[1]
                    year_vals = {}
                    for r in records:
                        if r["value"] is None:
                            continue
                        # World Bank API 的日期字段是 "date"（如 "2024"，月度为 "2024M05"），
                        # 部分旧响应才用 "year"
                        raw = str(r.get("date") or r.get("year") or "")
                        digits = raw[:4]
                        if digits.isdigit():
                            year_vals[int(digits)] = float(r["value"])
                    if year_vals:
                        s = pd.Series(year_vals)
                        s.index.name = "year"
                        return s.sort_index()
                # 无数据
                return pd.Series(dtype=float)
            elif resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            else:
                logger.warning(
                    f"WB API error: {resp.status_code} for {country_iso3}/{indicator}"
                )
                time.sleep(1)
        except requests.RequestException as e:
            logger.warning(f"WB request failed (attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)

    return pd.Series(dtype=float)


def _wb_fetch_multi(
    indicator: str,
    countries: list,
    date_start: int = 2015,
    date_end: int = None,
) -> pd.DataFrame:
    """
    从 World Bank 获取多个国家同一指标。
    返回 DataFrame: index=year, columns=country names.
    """
    frames = {}
    for c in countries:
        iso3 = COUNTRY_ISO3.get(c)
        if not iso3:
            continue
        s = _wb_fetch_indicator(iso3, indicator, date_start, date_end)
        if s is not None and len(s) > 0:
            frames[c] = s

    if not frames:
        return pd.DataFrame()

    df = pd.DataFrame(frames)
    df.index = df.index.astype(int)
    return df


# ═════════════════════════════════════════════════════════════
#  公开 API 函数
# ═════════════════════════════════════════════════════════════

def fetch_gdp_data(
    countries: Optional[list] = None,
    years: int = 10,
) -> dict:
    """
    获取 GDP 数据（当前美元计值 和 年增长率）。

    Parameters
    ----------
    countries : list, optional
        国家名列表，默认六国。
    years : int
        回溯年数，默认 10 年。

    Returns
    -------
    dict with keys:
        - 'gdp_usd' : DataFrame — 各国 GDP（当前亿美元）
        - 'gdp_growth' : DataFrame — GDP 年增长率（%）
    """
    if countries is None:
        countries = list(COUNTRY_CODES.keys())

    end_year = datetime.now().year
    start_year = end_year - years

    # ── GDP（当前美元） ──
    gdp_usd = _wb_fetch_multi(
        "NY.GDP.MKTP.CD", countries, start_year, end_year
    )
    if not gdp_usd.empty:
        # 转换为亿美元
        gdp_usd = gdp_usd.div(1e8).round(2)

    # ── GDP 年增长率（%） ──
    gdp_growth = _wb_fetch_multi(
        "NY.GDP.MKTP.KD.ZG", countries, start_year, end_year
    )
    if not gdp_growth.empty:
        gdp_growth = gdp_growth.round(2)

    return {"gdp_usd": gdp_usd, "gdp_growth": gdp_growth}


def fetch_cpi_data(
    countries: Optional[list] = None,
    years: int = 10,
) -> pd.DataFrame:
    """
    获取 CPI 通胀率（消费者价格指数年变化率 %）。

    数据源: World Bank - FP.CPI.TOTL.ZG
    """
    if countries is None:
        countries = list(COUNTRY_CODES.keys())

    end_year = datetime.now().year
    start_year = end_year - years

    cpi = _wb_fetch_multi("FP.CPI.TOTL.ZG", countries, start_year, end_year)
    if not cpi.empty:
        cpi = cpi.round(2)
    return cpi


def fetch_pmi_data() -> pd.DataFrame:
    """
    获取中国 PMI 数据（制造业 PMI）。

    数据源: akshare — 中国采购经理人指数
    返回 DataFrame:
        index=日期 (period:str 如 '2024-01')
        columns=['制造业PMI', '生产指数', '新订单指数', ...]
    """
    try:
        import akshare as ak

        df = ak.pmi_china()  # 返回 DateFrame

        # 标准化列名
        df.columns = [str(c).strip() for c in df.columns]

        # 寻找日期/月份列
        date_cols = [c for c in df.columns if "月" in str(c) or "日期" in str(c) or "时间" in str(c)]
        if date_cols:
            df = df.set_index(date_cols[0])
        elif "index" in str(df.index.name).lower() or df.index.name is None:
            # 尝试用第一列做 index
            first_col = df.columns[0]
            df = df.set_index(first_col)

        # 保留关键列
        keep_cols = []
        for kw in ["制造业", "PMI", "生产", "新订单", "从业人员"]:
            matched = [c for c in df.columns if kw in str(c)]
            keep_cols.extend(matched)
        keep_cols = list(set(keep_cols))

        if keep_cols:
            df = df[keep_cols]

        # 转数值
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.index = df.index.astype(str)
        return df

    except ImportError:
        logger.warning("akshare not installed. Cannot fetch PMI data.")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Failed to fetch PMI data via akshare: {e}")
        return pd.DataFrame()


def fetch_china_indicators() -> dict:
    """
    获取中国主要经济指标（CPI, GDP, PMI, 工业增加值, 固投, 零售, 进出口, M2, 贷款增长）。

    数据源: akshare

    Returns
    -------
    dict with keys:
        - 'cpi': DataFrame     — CPI 同比 (%)
        - 'ppi': DataFrame     — PPI 同比 (%)
        - 'gdp': DataFrame     — GDP 当季同比 (%)
        - 'pmi': DataFrame     — 制造业 PMI
        - 'industrial': DataFrame  — 工业增加值同比 (%)
        - 'fixed_asset': DataFrame — 固定资产投资累计同比 (%)
        - 'retail': DataFrame  — 社会消费品零售总额同比 (%)
        - 'trade': DataFrame   — 进出口数据 (出口, 进口, 贸易差额 亿美元)
        - 'money_supply': DataFrame — M2 同比 (%)
    """
    results = {}

    try:
        import akshare as ak

        # ── CPI ──
        try:
            df_cpi = ak.china_cpi_monthly()
            df_cpi = _clean_china_monthly(df_cpi, "cpi", "当月同比")
            results["cpi"] = df_cpi
        except Exception as e:
            logger.warning(f"akshare china_cpi_monthly failed: {e}")

        # ── PPI ──
        try:
            df_ppi = ak.china_ppi_monthly()
            df_ppi = _clean_china_monthly(df_ppi, "ppi", "当月同比")
            results["ppi"] = df_ppi
        except Exception as e:
            logger.warning(f"akshare china_ppi_monthly failed: {e}")

        # ── GDP ──
        try:
            df_gdp = ak.china_gdp()
            # GDP 季度数据
            df_gdp = _clean_china_quarterly(df_gdp)
            results["gdp"] = df_gdp
        except Exception as e:
            logger.warning(f"akshare china_gdp failed: {e}")

        # ── PMI（已单独） ──
        results["pmi"] = fetch_pmi_data()

        # ── 工业增加值 ──
        try:
            df_ind = ak.china_industrial_production_yoy()
            df_ind = _clean_china_monthly(df_ind, "industrial", None)
            results["industrial"] = df_ind
        except Exception as e:
            logger.warning(f"akshare china_industrial_production failed: {e}")

        # ── 固定资产投资 ──
        try:
            df_fai = ak.china_fixed_investment_yoy()
            df_fai = _clean_china_monthly(df_fai, "fixed_asset", None)
            results["fixed_asset"] = df_fai
        except Exception as e:
            logger.warning(f"akshare china_fixed_investment failed: {e}")

        # ── 社会消费品零售总额 ──
        try:
            df_retail = ak.china_retail_sales_yoy()
            df_retail = _clean_china_monthly(df_retail, "retail", None)
            results["retail"] = df_retail
        except Exception as e:
            logger.warning(f"akshare china_retail_sales failed: {e}")

        # ── 进出口贸易 ──
        try:
            df_trade = ak.china_trade_balance()
            results["trade"] = _clean_china_trade(df_trade)
        except Exception as e:
            logger.warning(f"akshare china_trade_balance failed: {e}")

        # ── M2 货币供应量 ──
        try:
            df_m2 = ak.china_money_supply()
            results["money_supply"] = _clean_china_money_supply(df_m2)
        except Exception as e:
            logger.warning(f"akshare china_money_supply failed: {e}")

    except ImportError:
        logger.warning("akshare not installed. Cannot fetch China indicators.")
    except Exception as e:
        logger.warning(f"fetch_china_indicators general error: {e}")

    return results


def fetch_fred_series(
    series_id: str,
    start_date: str = "2015-01-01",
) -> pd.Series:
    """
    从 FRED 获取美国经济指标时间序列。

    使用 pandas-datareader 访问 FRED（无需 API Key）。

    Parameters
    ----------
    series_id : str
        FRED 系列代码:
        - 'GDP'       — 名义 GDP
        - 'UNRATE'    — 失业率
        - 'CPIAUCSL'  — CPI（居民消费价格指数）
        - 'FEDFUNDS'  — 联邦基金利率
    start_date : str
        起始日期 'YYYY-MM-DD'

    Returns
    -------
    pd.Series with datetime index
    """
    try:
        from pandas_datareader.data import DataReader

        df = DataReader(series_id, "fred", start=start_date)
        s = df.iloc[:, 0]
        return s
    except ImportError:
        logger.warning("pandas-datareader not installed.")
        return pd.Series(dtype=float)
    except Exception as e:
        logger.warning(f"FRED fetch error for {series_id}: {e}")
        return pd.Series(dtype=float)


def fetch_us_gdp_quarterly(start_year: int = 2015) -> pd.DataFrame:
    """
    用 FRED 获取美国季度 GDP（GDPC1 — 实际 GDP）和 GDP 增速。

    Returns DataFrame with columns ['date', 'GDP_current', 'GDP_growth']
    """
    try:
        gdp = fetch_fred_series("GDPC1", f"{start_year}-01-01")
        if gdp.empty:
            return pd.DataFrame()

        df = gdp.reset_index()
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"])
        df["year_quarter"] = df["date"].dt.to_period("Q").astype(str)

        # 计算环比折年率 (近似)
        df["GDP_growth"] = df["value"].pct_change(4) * 100

        # 重采样到年度
        df_yearly = df.set_index("date").resample("YE").mean().reset_index()
        df_yearly["year"] = df_yearly["date"].dt.year.astype(int)
        df_yearly = df_yearly.rename(columns={
            "value": "GDP_real",
            "GDP_growth": "avg_growth",
        })[["year", "GDP_real", "avg_growth"]]
        df_yearly["avg_growth"] = df_yearly["avg_growth"].round(2)

        return df_yearly

    except Exception as e:
        logger.warning(f"fetch_us_gdp_quarterly error: {e}")
        return pd.DataFrame()


# ═════════════════════════════════════════════════════════════
#  内部辅助函数
# ═════════════════════════════════════════════════════════════

def _clean_china_monthly(df: pd.DataFrame, key: str, value_col: Optional[str]) -> pd.DataFrame:
    """标准化中国月度数据：统一 index 为 'YYYY-MM' 格式，只保留数值列。"""
    if df.empty:
        return df

    # 寻找日期列
    for col in df.columns:
        col_str = str(col).strip()
        if any(kw in col_str for kw in ["月", "日期", "时间", "period", "index"]):
            df = df.set_index(col)
            break

    # 如果 index 是 datetime，转为 'YYYY-MM'
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index.strftime("%Y-%m")
    else:
        # 试着从 index 提取年份月份
        new_index = []
        for idx in df.index:
            s = str(idx).strip()
            if len(s) >= 7 and s[:4].isdigit():
                # 尝试格式修正: "2024年1月" -> "2024-01"
                s = s.replace("年", "-").replace("月", "").replace(" ", "")
                if s.count("-") == 0 and len(s) >= 6:
                    s = s[:4] + "-" + s[4:]
                new_index.append(s)
            else:
                new_index.append(s)
        df.index = new_index

    # 找到数值列
    numeric_cols = []
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if df[col].notna().sum() > 0:
                numeric_cols.append(col)
        except (ValueError, TypeError):
            continue

    if value_col and value_col in df.columns:
        df = df[[value_col]]
    elif numeric_cols:
        df = df[numeric_cols[:3]]  # 保留前 3 列以防过多

    return df


def _clean_china_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    """标准化中国季度 GDP 数据。"""
    if df.empty:
        return df

    # 尝试找年份列和数值列
    year_col = None
    value_col = None
    for col in df.columns:
        c = str(col).strip()
        if "年" in c or "year" in c.lower():
            year_col = col
        # 找同比增长列
        if any(kw in c for kw in ["同比", "growth", "GDP"]):
            value_col = col

    if year_col and value_col:
        result = df[[year_col, value_col]].copy()
        result.columns = ["year", "value"]
        result["year"] = pd.to_numeric(result["year"], errors="coerce")
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result = result.dropna()
        result = result.set_index("year")
        return result

    return df


def _clean_china_trade(df: pd.DataFrame) -> pd.DataFrame:
    """标准化中国贸易数据。"""
    if df.empty:
        return df

    # akshare 的 china_trade_balance 通常返回 出口(亿美元), 进口(亿美元), 贸易差额(亿美元)
    # 按月度 index
    try:
        # 尝试 index 转 datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            # 假设第一列是日期
            for col in df.columns:
                if "月" in str(col) or "日期" in str(col) or "时间" in str(col):
                    df = df.set_index(col)
                    break

        # 全转数值
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            except (ValueError, TypeError):
                continue

        # 标准化列名
        rename_map = {}
        for col in df.columns:
            c = str(col)
            if "出口" in c or "export" in c.lower():
                rename_map[col] = "export"
            elif "进口" in c or "import" in c.lower():
                rename_map[col] = "import"
            elif "差额" in c or "balance" in c.lower():
                rename_map[col] = "balance"
        if rename_map:
            df = df.rename(columns=rename_map)

        # index 格式化为 YYYY-MM
        if isinstance(df.index, pd.DatetimeIndex):
            df.index = df.index.strftime("%Y-%m")
        else:
            df.index = [str(i).replace("年", "-").replace("月", "") for i in df.index]

        return df

    except Exception as e:
        logger.warning(f"Trade data cleaning error: {e}")
        return df


def _clean_china_money_supply(df: pd.DataFrame) -> pd.DataFrame:
    """标准化中国货币供应量数据。"""
    if df.empty:
        return df

    # akshare 的 china_money_supply 一般包含 M2 同比
    try:
        # 找 M2 同比 列
        m2_col = None
        for col in df.columns:
            c = str(col).strip()
            if "M2" in c and ("同比" in c or "同比" in str(col)):
                m2_col = col
                break

        # 找日期列
        date_col = None
        for col in df.columns:
            if any(kw in str(col) for kw in ["月", "日期"]):
                date_col = col
                break

        if date_col and m2_col:
            df = df[[date_col, m2_col]].copy()
            df.columns = ["date", "M2_yoy"]
            df["M2_yoy"] = pd.to_numeric(df["M2_yoy"], errors="coerce")
            df["date"] = df["date"].astype(str).str.replace("年", "-").str.replace("月", "")
            df = df.set_index("date").dropna()
            return df

        return df

    except Exception as e:
        logger.warning(f"Money supply cleaning error: {e}")
        return df


# ═════════════════════════════════════════════════════════════
#  数据汇总（用于首页概览卡片）
# ═════════════════════════════════════════════════════════════

def fetch_latest_indicators() -> dict:
    """
    获取各国最新关键经济指标，用于首页展示。

    Returns
    -------
    dict: {
        'GDP_latest': {country: value_billion_usd},
        'GDP_growth_latest': {country: value_percent},
        'CPI_latest': {country: value_percent},
        'US_unemployment': float or None,
        'China_PMI': float or None,
    }
    """
    result = {
        "GDP_latest": {},
        "GDP_growth_latest": {},
        "CPI_latest": {},
        "US_unemployment": None,
        "China_PMI": None,
    }

    # ── GDP 最新值 ──
    gdp_data = fetch_gdp_data(years=2)
    if not gdp_data["gdp_usd"].empty:
        for c in gdp_data["gdp_usd"].columns:
            vals = gdp_data["gdp_usd"][c].dropna()
            if not vals.empty:
                result["GDP_latest"][c] = vals.iloc[-1]

    if not gdp_data["gdp_growth"].empty:
        for c in gdp_data["gdp_growth"].columns:
            vals = gdp_data["gdp_growth"][c].dropna()
            if not vals.empty:
                result["GDP_growth_latest"][c] = vals.iloc[-1]

    # ── CPI 最新值 ──
    cpi_data = fetch_cpi_data(years=2)
    if not cpi_data.empty:
        for c in cpi_data.columns:
            vals = cpi_data[c].dropna()
            if not vals.empty:
                result["CPI_latest"][c] = vals.iloc[-1]

    # ── 美国失业率 ──
    unemp = fetch_fred_series("UNRATE")
    if not unemp.empty:
        result["US_unemployment"] = round(unemp.iloc[-1], 1)

    # ── 中国 PMI ──
    pmi_df = fetch_pmi_data()
    if not pmi_df.empty:
        cols = [c for c in pmi_df.columns if "PMI" in str(c) or "制造业" in str(c)]
        if cols:
            last_row = pmi_df[cols].iloc[-1]
            result["China_PMI"] = round(last_row.iloc[0], 1)

    return result
