from __future__ import annotations

from urllib.parse import urlparse

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP

from src.options.bse_service import BSEOptionsError, BSEOptionsService


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None) -> None:
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, params=None, timeout=None):
        self.calls.append((urlparse(url).path, dict(params or {})))
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP call: {url} params={params}")
        return self.responses.pop(0)


def _underlyings_payload() -> dict:
    return {
        "Table": [
            {"UlaCODE": "SENSEX", "scrip_cd": 1},
            {"UlaCODE": "BANKEX", "scrip_cd": 12},
        ]
    }


def _expiries_payload(*expiries: str) -> dict:
    return {
        "Table": [],
        "Table1": [{"ExpiryDate": expiry} for expiry in expiries],
        "Table2": [],
    }


def _chain_payload(*rows: dict, as_of: str = "25 Jun 2026 | 15:30 ") -> dict:
    return {
        "Table": list(rows),
        "ASON": {"DT_TM": as_of},
        "tot_C_Open_Interest": "10",
        "tot_C_Vol_Traded": "20",
        "tot_Open_Interest": "30",
        "tot_Vol_Traded": "40",
    }


def _sensex_row() -> dict:
    return {
        "C_Open_Interest": "29",
        "C_Absolute_Change_OI": "5",
        "C_Last_Trd_Price": "12635.00",
        "C_Vol_Traded": "60",
        "C_BidPrice": "12620.00",
        "C_OfferPrice": "12650.00",
        "Strike_Price": "64,900.00",
        "Strike_Price1": "64900.00",
        "Vol_Traded": "9996",
        "Last_Trd_Price": "0.05",
        "Absolute_Change_OI": "724",
        "Open_Interest": "1159",
        "BidPrice": "0.05",
        "OfferPrice": "0.10",
        "Ula_Code": "SENSEX",
        "UlaValue": "77100.47",
        "IV": "86.2609582522",
        "C_IV": "257.2355725306",
    }


def _bankex_blank_row() -> dict:
    return {
        "C_Open_Interest": "",
        "C_Absolute_Change_OI": "",
        "C_Last_Trd_Price": "",
        "C_Vol_Traded": "",
        "C_BidPrice": "",
        "C_OfferPrice": "",
        "Strike_Price": "49,600.00",
        "Strike_Price1": "49600.00",
        "Vol_Traded": "",
        "Last_Trd_Price": "",
        "Absolute_Change_OI": "",
        "Open_Interest": "",
        "BidPrice": "",
        "OfferPrice": "",
        "Ula_Code": "BANKEX",
        "UlaValue": "65599.62",
        "IV": "",
        "C_IV": "",
    }


class TestBSEOptionsService:
    def test_successful_fetch_normalizes_schema(self):
        session = _FakeSession(
            [
                _FakeResponse(json_data=_underlyings_payload()),
                _FakeResponse(json_data=_expiries_payload("25 Jun 2026", "02 Jul 2026")),
                _FakeResponse(json_data=_chain_payload(_sensex_row())),
            ]
        )
        svc = BSEOptionsService(session=session)

        chain = svc.get_option_chain("SENSEX")

        assert chain["records"]["expiryDates"] == ["25 Jun 2026", "02 Jul 2026"]
        assert chain["records"]["underlyingValue"] == pytest.approx(77100.47)
        assert chain["source_meta"]["exchange"] == "BSE"
        row = chain["records"]["data"][0]
        assert row["strikePrice"] == pytest.approx(64900.0)
        assert row["expiryDate"] == "25 Jun 2026"
        assert row["CE"]["openInterest"] == 29
        assert row["CE"]["lastPrice"] == pytest.approx(12635.0)
        assert row["PE"]["openInterest"] == 1159
        assert row["PE"]["impliedVolatility"] == pytest.approx(86.2609582522)

    def test_parser_maps_blank_values_to_none(self):
        session = _FakeSession(
            [
                _FakeResponse(json_data=_underlyings_payload()),
                _FakeResponse(json_data=_expiries_payload("25 Jun 2026")),
                _FakeResponse(json_data=_chain_payload(_bankex_blank_row())),
            ]
        )
        svc = BSEOptionsService(session=session)

        chain = svc.get_option_chain("BANKEX")

        row = chain["records"]["data"][0]
        assert row["strikePrice"] == pytest.approx(49600.0)
        assert row["CE"] is None
        assert row["PE"] is None
        assert chain["records"]["underlyingValue"] == pytest.approx(65599.62)

    def test_available_expiries_uses_official_expiry_endpoint(self):
        session = _FakeSession(
            [
                _FakeResponse(json_data=_underlyings_payload()),
                _FakeResponse(json_data=_expiries_payload("25 Jun 2026", "30 Jul 2026")),
            ]
        )
        svc = BSEOptionsService(session=session)

        expiries = svc.available_expiries("BANKEX")

        assert expiries == ["25 Jun 2026", "30 Jul 2026"]
        assert session.calls[-1] == (
            "/BseIndiaAPI/api/ddlExpiry_IV/w",
            {"ProductType": "IO", "scrip_cd": "12"},
        )

    def test_empty_response_raises_structured_error(self):
        session = _FakeSession(
            [
                _FakeResponse(json_data=_underlyings_payload()),
                _FakeResponse(json_data=_expiries_payload("25 Jun 2026")),
                _FakeResponse(json_data=_chain_payload()),
            ]
        )
        svc = BSEOptionsService(session=session)

        with pytest.raises(BSEOptionsError) as exc:
            svc.get_option_chain("SENSEX")

        assert exc.value.code == "BSE_EMPTY_CHAIN"

    def test_http_failure_raises_structured_error(self):
        session = _FakeSession([_FakeResponse(status_code=503, json_data={})])
        svc = BSEOptionsService(session=session)

        with pytest.raises(BSEOptionsError) as exc:
            svc.available_expiries("SENSEX")

        assert exc.value.code == "BSE_HTTP_ERROR"
        assert exc.value.details["status_code"] == 503

    def test_malformed_payload_raises_structured_error(self):
        session = _FakeSession(
            [
                _FakeResponse(json_data=_underlyings_payload()),
                _FakeResponse(json_data={"Table": []}),
            ]
        )
        svc = BSEOptionsService(session=session)

        with pytest.raises(BSEOptionsError) as exc:
            svc.available_expiries("SENSEX")

        assert exc.value.code == "BSE_MALFORMED_PAYLOAD"


class TestBSEOptionsTools:
    def _options_mcp(self):
        from src.tools import options

        mcp = _FastMCP("test")
        options.register(mcp)
        return {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    def test_registration_adds_bse_option_tools(self):
        tools = self._options_mcp()

        assert "get_sensex_option_chain" in tools
        assert "get_bankex_option_chain" in tools

    def test_sensex_tool_matches_existing_chain_shape(self, monkeypatch):
        from src.tools import options as options_tools

        chain = {
            "records": {
                "underlyingValue": 77100.47,
                "expiryDates": ["25 Jun 2026"],
                "data": [
                    {
                        "strikePrice": 77100.0,
                        "expiryDate": "25 Jun 2026",
                        "CE": {
                            "openInterest": 100,
                            "changeinOpenInterest": 5,
                            "totalTradedVolume": 50,
                            "impliedVolatility": 12.5,
                            "lastPrice": 200.0,
                            "bidprice": 199.0,
                            "askPrice": 201.0,
                        },
                        "PE": {
                            "openInterest": 110,
                            "changeinOpenInterest": 7,
                            "totalTradedVolume": 60,
                            "impliedVolatility": 13.5,
                            "lastPrice": 210.0,
                            "bidprice": 209.0,
                            "askPrice": 211.0,
                        },
                    }
                ],
            }
        }

        class _Svc:
            def get_option_chain(self, symbol, expiry=None):
                return chain

        monkeypatch.setattr(options_tools, "get_bse_options_service", lambda: _Svc())
        tool = self._options_mcp()["get_sensex_option_chain"].fn

        result = tool(expiry="25 Jun 2026", atm_range=1)

        assert result["symbol"] == "SENSEX"
        assert result["underlying_value"] == pytest.approx(77100.47)
        assert result["available_expiries"] == ["25 Jun 2026"]
        assert result["total_strikes"] == 1
        assert result["strikes"][0]["CE"]["oi"] == 100
        assert result["strikes"][0]["PE"]["ltp"] == pytest.approx(210.0)

    def test_sensex_and_nifty_tools_share_identical_schema(self, monkeypatch):
        from src.tools import options as options_tools

        chain = {
            "records": {
                "underlyingValue": 77100.47,
                "expiryDates": ["25 Jun 2026"],
                "data": [
                    {
                        "strikePrice": 77100.0,
                        "expiryDate": "25 Jun 2026",
                        "CE": {
                            "openInterest": 100,
                            "changeinOpenInterest": 5,
                            "totalTradedVolume": 50,
                            "impliedVolatility": 12.5,
                            "lastPrice": 200.0,
                            "bidprice": 199.0,
                            "askPrice": 201.0,
                        },
                        "PE": {
                            "openInterest": 110,
                            "changeinOpenInterest": 7,
                            "totalTradedVolume": 60,
                            "impliedVolatility": 13.5,
                            "lastPrice": 210.0,
                            "bidprice": 209.0,
                            "askPrice": 211.0,
                        },
                    }
                ],
            }
        }

        class _NSESvc:
            def get_option_chain(self, symbol, expiry=None):
                return chain

        class _BSESvc:
            def get_option_chain(self, symbol, expiry=None):
                return chain

        monkeypatch.setattr(options_tools, "get_options_service", lambda: _NSESvc())
        monkeypatch.setattr(options_tools, "get_bse_options_service", lambda: _BSESvc())
        tools = self._options_mcp()

        nifty = tools["get_nifty_option_chain"].fn(expiry="25 Jun 2026", atm_range=1)
        sensex = tools["get_sensex_option_chain"].fn(expiry="25 Jun 2026", atm_range=1)

        assert set(nifty.keys()) == set(sensex.keys())
        assert type(nifty["underlying_value"]) is type(sensex["underlying_value"])
        assert type(nifty["available_expiries"]) is type(sensex["available_expiries"])
        assert type(nifty["strikes"]) is type(sensex["strikes"])
        assert set(nifty["strikes"][0].keys()) == set(sensex["strikes"][0].keys())
        assert set(nifty["strikes"][0]["CE"].keys()) == set(sensex["strikes"][0]["CE"].keys())
        assert set(nifty["strikes"][0]["PE"].keys()) == set(sensex["strikes"][0]["PE"].keys())


class TestBSEOptionMetadata:
    def _meta_mcp(self):
        from src.tools import meta_tools, options

        mcp = _FastMCP("test")
        options.register(mcp)
        meta_tools.register(mcp)
        return {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    def test_capabilities_include_bse_support(self):
        tools = self._meta_mcp()
        result = tools["get_capabilities"].fn()

        assert result["data"]["capabilities"]["bse_index_options"] is True
        assert result["data"]["data_lag"]["get_sensex_option_chain"] == "5-15 min"
        assert result["data"]["data_lag"]["get_bankex_option_chain"] == "5-15 min"

    def test_tool_health_lists_new_bse_tools(self):
        tools = self._meta_mcp()
        result = tools["get_tool_health"].fn()
        detail = result["data"]["tools"]

        assert detail["get_sensex_option_chain"]["status"] == "healthy"
        assert detail["get_sensex_option_chain"]["data_lag"] == "5-15 min"
        assert detail["get_bankex_option_chain"]["status"] == "healthy"
        assert detail["get_bankex_option_chain"]["data_lag"] == "5-15 min"
