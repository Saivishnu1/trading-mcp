from __future__ import annotations

import datetime


def get_calendar_index_key(symbol: str) -> str:
    sym = symbol.upper().strip()
    if "BANKNIFTY" in sym:
        return "banknifty"
    if "FINNIFTY" in sym:
        return "finnifty"
    if "MIDCPNIFTY" in sym or "MIDCAP" in sym:
        return "midcap_nifty"
    if "SENSEX" in sym:
        return "sensex"
    if "BANKEX" in sym:
        return "bankex"
    if "NIFTY" in sym:
        return "nifty"
    return "nifty"


class MarketNarrator:

    def narrate(self, data: dict, missing_data: list[str] | None = None) -> list[str]:
        obs = []

        if missing_data:
            obs.append(
                "Data unavailable for: " + ", ".join(missing_data) +
                " — treat related fields as absent, not zero."
            )

        # 1. Chart observations
        chart = data.get("chart", {})
        if isinstance(chart, dict):
            chart_obs = chart.get("observations", [])
            if chart_obs:
                obs.extend(chart_obs)

        # 2. Candlestick patterns
        candlestick = data.get("candlestick", {})
        if isinstance(candlestick, dict):
            candle_obs = candlestick.get("observations", [])
            if candle_obs:
                obs.extend(candle_obs)

        # 3. Chart patterns
        chart_patterns = data.get("chart_patterns", {})
        if isinstance(chart_patterns, dict):
            cp_obs = chart_patterns.get("observations", [])
            if cp_obs:
                obs.extend(cp_obs)

        # 4. Options
        options = data.get("options", {})
        if isinstance(options, dict):
            opt_obs = options.get("observations", [])
            if opt_obs:
                # Filter out cache metadata messages if present to keep it strictly factual
                cleaned_opt_obs = [o for o in opt_obs if "cached" not in o.lower()]
                obs.extend(cleaned_opt_obs)

        # 5. VIX
        vix = data.get("vix", {})
        if isinstance(vix, dict) and vix.get("level") is not None:
            vix_level = vix.get("level")
            vix_interp = vix.get("interpretation", "")
            vix_str = f"VIX {vix_level:.1f}"
            if vix_interp:
                vix_str += f" — {vix_interp.lower()}"
            obs.append(vix_str)

        # 6. Global Pulse
        global_pulse = data.get("global", {})
        if isinstance(global_pulse, dict):
            assets = global_pulse.get("assets", {})
            if isinstance(assets, dict):
                for k, key_name in [("gold", "Gold"), ("crude_oil", "Crude Oil"), ("dxy", "US Dollar Index")]:
                    asset = assets.get(k)
                    if isinstance(asset, dict):
                        chg = asset.get("change_pct")
                        impact = asset.get("india_impact")
                        if chg is not None:
                            obs.append(f"{key_name} {chg:+.2f}% — {impact}")

        # 7. Calendar / Expiry
        calendar = data.get("calendar", {})
        if isinstance(calendar, dict):
            symbol = data.get("symbol", "NIFTY")
            idx_key = get_calendar_index_key(symbol)
            exp_date = calendar.get("expiries", {}).get(idx_key)
            days = calendar.get("days_to_expiry", {}).get(idx_key)
            if exp_date and days is not None:
                try:
                    d = datetime.date.fromisoformat(exp_date)
                    date_str = d.strftime("%b %d")
                    weekday = d.strftime("%A")
                except Exception:
                    date_str = exp_date
                    weekday = ""

                day_suffix = "day" if days == 1 else "days"
                if days == 0:
                    obs.append(f"Expiry today ({date_str}) — theta accelerating.")
                elif days == 1:
                    obs.append(f"Expiry tomorrow ({date_str}) — theta accelerating.")
                else:
                    obs.append(f"Expiry {weekday} {date_str} — {days} {day_suffix} away.")

        return obs
