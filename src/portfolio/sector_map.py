"""
NSE sector mapping for top 200+ symbols.
Used by the portfolio analyzer to group holdings by sector.
"""
from __future__ import annotations

SECTOR_MAP: dict[str, str] = {
    # Banking
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "AXISBANK": "Banking", "KOTAKBANK": "Banking", "INDUSINDBK": "Banking",
    "BANKBARODA": "Banking", "FEDERALBNK": "Banking", "IDFCFIRSTB": "Banking",
    "PNB": "Banking", "CANBK": "Banking", "UNIONBANK": "Banking",
    "BANDHANBNK": "Banking", "AUBANK": "Banking", "YESBANK": "Banking",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TECHM": "IT", "MPHASIS": "IT", "PERSISTENT": "IT", "COFORGE": "IT",
    "LTIM": "IT", "OFSS": "IT", "HEXAWARE": "IT",
    # Energy & Oil
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "IOC": "Energy", "GAIL": "Energy", "HINDPETRO": "Energy",
    "PETRONET": "Energy", "MGL": "Energy", "IGL": "Energy",
    # Auto
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto", "EICHERMOT": "Auto",
    "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "MOTHERSON": "Auto",
    # Pharma
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "BIOCON": "Pharma", "AUROPHARMA": "Pharma",
    "LUPIN": "Pharma", "TORNTPHARM": "Pharma", "ALKEM": "Pharma",
    # FMCG
    "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "COLPAL": "FMCG", "EMAMILTD": "FMCG", "TATACONSUM": "FMCG",
    # Metals & Mining
    "JSWSTEEL": "Metals", "TATASTEEL": "Metals", "HINDALCO": "Metals",
    "VEDL": "Metals", "SAIL": "Metals", "NMDC": "Metals",
    "COALINDIA": "Mining", "HINDCOPPER": "Metals",
    # Infrastructure & Capital Goods
    "LT": "Infrastructure", "ADANIPORTS": "Infrastructure",
    "ADANIENT": "Conglomerate", "SIEMENS": "Capital Goods",
    "ABB": "Capital Goods", "BHEL": "Capital Goods",
    "HAVELLS": "Capital Goods", "CUMMINSIND": "Capital Goods",
    # Power
    "NTPC": "Power", "POWERGRID": "Power", "ADANIGREEN": "Power",
    "TATAPOWER": "Power", "NHPC": "Power", "SJVN": "Power",
    # Cement
    "ULTRACEMCO": "Cement", "SHREECEM": "Cement", "AMBUJACEM": "Cement",
    "ACC": "Cement", "DALMIACEMT": "Cement", "JKCEMENT": "Cement",
    # Consumer & Retail
    "TITAN": "Consumer", "ASIANPAINT": "Consumer", "PIDILITIND": "Consumer",
    "BERGEPAINT": "Consumer", "VOLTAS": "Consumer",
    "WHIRLPOOL": "Consumer", "RELAXO": "Consumer",
    # NBFC & Finance
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "CHOLAFIN": "NBFC",
    "MUTHOOTFIN": "NBFC", "MANAPPURAM": "NBFC", "LICHSGFIN": "NBFC",
    "SBICARD": "NBFC", "HDFCAMC": "Asset Management",
    "NIPPONLIFE": "Asset Management", "ICICIGI": "Insurance",
    "ICICIPRULI": "Insurance", "HDFCLIFE": "Insurance", "SBILIFE": "Insurance",
    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom",
    # Real Estate
    "DLF": "Real Estate", "GODREJPROP": "Real Estate",
    "OBEROIRLTY": "Real Estate", "PRESTIGE": "Real Estate",
    # Healthcare
    "APOLLOHOSP": "Healthcare", "FORTIS": "Healthcare",
    "MAXHEALTH": "Healthcare", "METROPOLIS": "Healthcare",
    # Aviation & Transport
    "INDIGO": "Aviation", "GMRINFRA": "Infrastructure",
    # Specialty Chemicals
    "UPL": "Chemicals", "PIIND": "Chemicals", "DEEPAKNTR": "Chemicals",
    "AARTIIND": "Chemicals", "VINATIORGA": "Chemicals",
}


def get_sector(symbol: str) -> str:
    """Return sector for symbol, 'Other' if unknown.

    Strips exchange prefix (NSE:INFY → INFY) and suffix (INFY.NS → INFY)
    before lookup. Case-insensitive.
    """
    clean = symbol.upper().split(":")[-1].split(".")[0]
    return SECTOR_MAP.get(clean, "Other")
