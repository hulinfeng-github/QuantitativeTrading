"""
A股实时行情与历史K线数据获取模块
特点：专为主板定制（过滤科创板、创业板、北交所与ST股），支持腾讯/新浪极速API，具备本地缓存与失败重试
"""
import re
import json
import time
import requests
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import BASE_DIR, DATA_DIR, load_config

STOCK_LIST_CACHE = DATA_DIR / "main_board_stocks.json"

class DataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.qq.com"
        })

    @staticmethod
    def clean_code(code: str) -> str:
        """从任意格式（如 600519.SH, SH600519, sz000001, 000001.SZ）提取纯6位数字代码"""
        if not code:
            return ""
        # 提取纯数字
        digits = re.sub(r'[^0-9]', '', str(code).strip())
        return digits

    @classmethod
    def is_main_board(cls, code: str) -> bool:
        """
        判断是否为A股主板股票代码或主流场内ETF基金
        兼容：600519, 002156, 512890(红利低波), 561980(芯片设备), 159xxx 等
        沪市主板：600, 601, 603, 605；沪市ETF：51, 56, 58
        深市主板：000, 001, 002, 003；深市ETF：15, 16
        严格过滤高风险高门槛：科创板(688)、创业板(300)、北交所(8/4/920)
        """
        digits = cls.clean_code(code)
        if len(digits) != 6:
            return False
        # 沪市主板与场内主流ETF
        if digits.startswith(("600", "601", "603", "605", "51", "56", "58")):
            return True
        # 深市主板与场内主流ETF
        if digits.startswith(("000", "001", "002", "003", "15", "16")):
            return True
        return False

    @classmethod
    def format_symbol(cls, code: str) -> str:
        """格式化为带市场前缀的标准代码，如 sh600519, sh512890, sz002156, sh000001(上证指数), sh000300(沪深300)"""
        c = str(code).strip().lower()
        if c.startswith(("sh", "sz")):
            return c
        digits = cls.clean_code(code)
        if len(digits) == 6:
            if digits.startswith(("6", "5")):
                return f"sh{digits}"
            elif digits.startswith(("0", "1", "3")):
                return f"sz{digits}"
        return digits or c

    def search_stocks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        根据代码、名称或拼音进行模糊检索
        :param query: 如 '600519', '茅台', '比亚迪'
        :param limit: 最多返回匹配数
        """
        q = str(query).strip().lower()
        if not q:
            return []
        
        stocks = self.get_main_board_stock_list()
        matches = []
        
        # 纯数字优先匹配代码
        is_num = q.isdigit()
        for s in stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            sym = s.get("symbol", "")
            
            if is_num:
                if code.startswith(q) or code == q:
                    matches.append(s)
            else:
                clean_name = name.replace(" ", "").lower()
                clean_q = q.replace(" ", "")
                if clean_q in clean_name or q in sym.lower():
                    matches.append(s)
            if len(matches) >= limit:
                break
        return matches

    def resolve_symbol(self, query: str) -> Optional[Dict[str, str]]:
        """
        将用户输入的代码或股票名称解析为标准标的
        例如输入 '600519' 或 '茅台' 或 '贵州茅台'
        """
        q = str(query).strip()
        if not q:
            return None
        
        # 1. 尝试直接判断是否为主板代码
        if self.is_main_board(q):
            sym = self.format_symbol(q)
            code = self.clean_code(q)
            # 尝试获取名字
            stocks = self.get_main_board_stock_list()
            for s in stocks:
                if s.get("code") == code:
                    return {"code": code, "symbol": sym, "name": s.get("name", code)}
            return {"code": code, "symbol": sym, "name": code}

        # 2. 尝试从名称模糊搜索
        matches = self.search_stocks(q, limit=1)
        if matches:
            top = matches[0]
            return {
                "code": top["code"],
                "symbol": top["symbol"],
                "name": top["name"]
            }
        return None

    def get_main_board_stock_list(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        获取全A股主板股票清单（代码、名称）并缓存到本地
        自动剔除：科创板(688)、创业板(300)、北交所、ST股
        """
        if not force_refresh and STOCK_LIST_CACHE.exists():
            try:
                # 检查缓存时间是否在7天内
                mtime = STOCK_LIST_CACHE.stat().st_mtime
                if time.time() - mtime < 7 * 86400:
                    with open(STOCK_LIST_CACHE, "r", encoding="utf-8") as f:
                        stocks = json.load(f)
                        if len(stocks) > 1000:
                            return stocks
            except Exception:
                pass

        stocks = []
        try:
            # 优先从东方财富分段拉取沪深全市场股票
            for p in range(1, 40):
                url = (
                    "https://push2.eastmoney.com/api/qt/clist/get"
                    f"?pn={p}&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                    "&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
                    "&fields=f12,f14,f2,f3,f6"
                )
                resp = self.session.get(url, timeout=5)
                if resp.status_code != 200:
                    break
                data = resp.json().get("data")
                if not data or not data.get("diff"):
                    break
                diff = data["diff"]
                for item in diff:
                    code = str(item.get("f12", ""))
                    name = str(item.get("f14", ""))
                    # 严格只保留主板
                    if not self.is_main_board(code):
                        continue
                    # 严格剔除 ST, *ST, 退市
                    if "ST" in name.upper() or "退" in name:
                        continue
                    symbol = self.format_symbol(code)
                    stocks.append({
                        "code": code,
                        "name": name,
                        "symbol": symbol,
                        "price": item.get("f2", 0),
                        "change_pct": item.get("f3", 0),
                        "turnover": item.get("f6", 0)
                    })
                if len(diff) < 100:
                    break
        except Exception as e:
            print(f"东方财富列表拉取异常: {e}")

        # 如果东方财富由于网络受阻，从备用静态种子/新浪接口兜底
        if len(stocks) < 500:
            stocks = self._get_fallback_stock_list()

        if stocks:
            try:
                with open(STOCK_LIST_CACHE, "w", encoding="utf-8") as f:
                    json.dump(stocks, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return stocks

    def _get_fallback_stock_list(self) -> List[Dict[str, str]]:
        """兜底主流主板核心蓝筹与优质白马标的种子池"""
        core_seeds = [
            ("600519", "贵州茅台"), ("601318", "中国平安"), ("600036", "招商银行"),
            ("601857", "中国石油"), ("601398", "工商银行"), ("600900", "长江电力"),
            ("600030", "中信证券"), ("601088", "中国神华"), ("600887", "伊利股份"),
            ("601988", "中国银行"), ("600028", "中国石化"), ("601899", "紫金矿业"),
            ("600104", "上汽集团"), ("600050", "中国联通"), ("601668", "中国建筑"),
            ("600276", "恒瑞医药"), ("600309", "万华化学"), ("601628", "中国人寿"),
            ("000001", "平安银行"), ("000333", "美的集团"), ("000651", "格力电器"),
            ("000858", "五粮液"),   ("000725", "京东方A"),  ("002415", "海康威视"),
            ("000002", "万科A"),   ("002594", "比亚迪"),  ("000963", "华东医药"),
            ("002475", "立讯精密"), ("000768", "中航西飞"), ("002714", "牧原股份"),
            ("601138", "工业富联"), ("600418", "江淮汽车"), ("601919", "中远海控"),
            ("600048", "保利发展"), ("000799", "酒鬼酒"),   ("600809", "山西汾酒"),
            ("002304", "洋河股份"), ("601658", "邮储银行"), ("600111", "北方稀土"),
            ("600547", "山东黄金"), ("000063", "中兴通讯"), ("000425", "徐工机械"),
            ("600031", "三一重工"), ("601006", "大秦铁路"), ("600905", "三峡能源"),
            ("601288", "农业银行"), ("601328", "交通银行"), ("601985", "中国核电")
        ]
        return [{"code": c, "name": n, "symbol": self.format_symbol(c)} for c, n in core_seeds]

    def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取实时行情快照（腾讯极速行情API）
        :param symbols: 如 ['sh600519', 'sz000001']
        :return: 包含最新价、涨跌幅、成交量、成交金额、最高最低价等的字典
        """
        results = {}
        if not symbols:
            return results

        # 腾讯接口单批次最多支持约60-80只股票
        chunk_size = 60
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i : i + chunk_size]
            query_str = ",".join(chunk)
            url = f"https://qt.gtimg.cn/q={query_str}"
            try:
                resp = self.session.get(url, timeout=3)
                if resp.status_code != 200:
                    continue
                # 腾讯行情编码为 gbk
                text = resp.content.decode("gbk", errors="ignore")
                for line in text.strip().split(";"):
                    line = line.strip()
                    if not line or '="' not in line:
                        continue
                    m = re.match(r"v_(.*?)=\"(.*?)\"", line)
                    if not m:
                        continue
                    sym = m.group(1).strip()
                    fields = m.group(2).split("~")
                    if len(fields) < 35:
                        continue
                    # 字段解析
                    name = fields[1]
                    code = fields[2]
                    price = float(fields[3]) if fields[3] else 0.0
                    prev_close = float(fields[4]) if fields[4] else 0.0
                    open_price = float(fields[5]) if fields[5] else 0.0
                    volume = float(fields[6]) if fields[6] else 0.0 # 手
                    high = float(fields[33]) if len(fields) > 33 and fields[33] else price
                    low = float(fields[34]) if len(fields) > 34 and fields[34] else price
                    turnover = float(fields[37]) if len(fields) > 37 and fields[37] else 0.0 # 万元
                    change_pct = float(fields[32]) if len(fields) > 32 and fields[32] else 0.0

                    results[sym] = {
                        "symbol": sym,
                        "code": code,
                        "name": name,
                        "price": price,
                        "prev_close": prev_close,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "volume": volume,
                        "turnover": turnover * 10000, # 转换为元
                        "change_pct": change_pct,
                        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            except Exception as e:
                print(f"获取实时行情异常: {e}")
        return results

    def get_daily_kline(self, symbol: str, count: int = 650) -> Optional[pd.DataFrame]:
        """
        获取单只股票历史前复权日K线数据（腾讯财经接口）
        :param symbol: 如 'sh600519' 或 'sz000001'
        :param count: 获取K线根数（默认650根，满足RSRS的600天Z-score窗口）
        :return: DataFrame (date, open, close, high, low, volume)
        """
        sym = self.format_symbol(symbol)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{count},qfq"
        try:
            resp = self.session.get(url, timeout=5)
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", {})
            stock_data = data.get(sym, {})
            # 前复权字段名为 qfqday 或 day
            kline_list = stock_data.get("qfqday") or stock_data.get("day")
            if not kline_list:
                return None

            records = []
            for item in kline_list:
                if len(item) < 6:
                    continue
                records.append({
                    "date": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5])
                })
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            return df
        except Exception as e:
            print(f"拉取K线异常 {sym}: {e}")
            return None

    def get_minute_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取单只股票当日日内分时数据（1分钟级）
        返回 DataFrame: time, price, volume, amount, vwap, bias
        """
        sym = self.format_symbol(symbol)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={sym}"
        try:
            resp = self.session.get(url, timeout=4)
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", {}).get(sym, {}).get("data", {})
            raw_list = data.get("data", [])
            if not raw_list:
                return None

            records = []
            for item in raw_list:
                parts = item.split()
                if len(parts) < 4:
                    continue
                t_str = parts[0] # 如 "0930"
                t_formatted = f"{t_str[:2]}:{t_str[2:]}"
                price = float(parts[1])
                cum_vol = float(parts[2]) # 累计成交手
                cum_amt = float(parts[3]) # 累计成交金额（元）
                
                # VWAP: 累计成交金额 / (累计成交量 * 100)
                vwap = (cum_amt / (cum_vol * 100)) if cum_vol > 0 else price
                bias = ((price - vwap) / vwap) * 100 if vwap > 0 else 0.0

                records.append({
                    "time": t_formatted,
                    "price": price,
                    "cum_volume": cum_vol,
                    "cum_amount": cum_amt,
                    "vwap": round(vwap, 2),
                    "bias": round(bias, 2)
                })

            df = pd.DataFrame(records)
            return df
        except Exception as e:
            print(f"拉取分时数据异常 {sym}: {e}")
            return None

data_fetcher = DataFetcher()
