from __future__ import annotations


SYMBOL_DISPLAY_NAMES = {
    "159915.SZ": "易方达创业板交易型开放式指数证券投资基金",
    "510300.SH": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
    "511360.SH": "海富通中证短融交易型开放式指数证券投资基金",
    "159999.SZ": "永赢中证500交易型开放式指数证券投资基金（退市）",
    "588000.SH": "华夏上证科创板50成份交易型开放式指数证券投资基金",
    "512000.SH": "华宝中证全指证券公司交易型开放式指数证券投资基金",
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
