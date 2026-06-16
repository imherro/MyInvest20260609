from __future__ import annotations


SYMBOL_DISPLAY_NAMES = {
    "159915.SZ": "创业板ETF易方达",
    "510300.SH": "沪深300ETF华泰柏瑞",
    "511360.SH": "短融ETF海富通",
    "159999.SZ": "永赢中证500ETF（退市）",
    "588000.SH": "科创50ETF华夏",
    "512000.SH": "证券ETF华宝",
    "002920.SZ": "德赛西威",
    "301566.SZ": "达利凯普",
    "688167.SH": "炬光科技",
    "688170.SH": "德龙激光",
    "688603.SH": "天承科技",
    "688757.SH": "胜科纳米",
    "000300.SH": "沪深300指数",
    "000905.SH": "中证500指数",
    "CSI300": "沪深300指数",
    "CSI500": "中证500指数",
}


def symbol_name(symbol: str) -> str:
    return SYMBOL_DISPLAY_NAMES.get(symbol, symbol)


def display_symbol(symbol: str) -> str:
    name = symbol_name(symbol)
    if name == symbol:
        return symbol
    return f"{name}（{symbol}）"
