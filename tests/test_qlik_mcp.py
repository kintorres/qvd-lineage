"""Unit tests for qlik_mcp pure helper functions."""
import json
import sys
import os
import asyncio
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import qlik_mcp


# ---------------------------------------------------------------------------
# _extract_qvd_name_from_qri
# ---------------------------------------------------------------------------

def test_extract_qvd_name_from_full_path():
    result = qlik_mcp._extract_qvd_name_from_qri(
        "qri:datafile:dsg://tenant/space/Sales_Data.qvd"
    )
    assert result == "Sales_Data"


def test_extract_qvd_name_no_extension():
    result = qlik_mcp._extract_qvd_name_from_qri(
        "qri:datafile:dsg://tenant/space/Orders"
    )
    assert result == "Orders"


def test_extract_qvd_name_case_insensitive_extension():
    result = qlik_mcp._extract_qvd_name_from_qri(
        "qri:datafile:dsg://tenant/space/Customers.QVD"
    )
    assert result == "Customers"


# ---------------------------------------------------------------------------
# _parse_qvd_fields_from_script
# ---------------------------------------------------------------------------

QVD_FIELDS = ["CustomerID", "OrderDate", "Amount", "Region", "ProductID"]


def test_parse_explicit_fields():
    script = "LOAD CustomerID, OrderDate, Amount FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["Amount", "CustomerID", "OrderDate"]


def test_parse_wildcard_returns_all_fields():
    script = "LOAD * FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == sorted(QVD_FIELDS)


def test_parse_renamed_field_returns_original():
    script = "LOAD CustomerID AS CustID, OrderDate FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["CustomerID", "OrderDate"]


def test_parse_expression_extracts_inner_field():
    script = "LOAD Year(OrderDate) AS OrderYear, CustomerID FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["CustomerID", "OrderDate"]


def test_parse_variable_path_resolved():
    script = (
        "SET vPath = 'lib://Data/';\n"
        "LOAD CustomerID FROM [$(vPath)Sales.qvd] (qvd);"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["CustomerID"]


def test_parse_variable_full_filename_substituted():
    """Variable holds the full QVD stem; must be expanded correctly."""
    script = (
        "SET vFile = 'Sales';\n"
        "LOAD CustomerID FROM [lib://Data/$(vFile).qvd] (qvd);"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["CustomerID"]


def test_parse_no_matching_qvd_returns_empty():
    script = "LOAD CustomerID FROM [lib://Data/Orders.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result is None


def test_parse_qvd_found_but_no_schema_match_returns_empty_list():
    script = "LOAD NonExistent1, NonExistent2 FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == []


def test_parse_only_keeps_fields_in_schema():
    script = "LOAD CustomerID, NonExistentField FROM [lib://Data/Sales.qvd] (qvd);"
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["CustomerID"]


def test_parse_multiline_load():
    script = (
        "LOAD\n"
        "    CustomerID,\n"
        "    OrderDate,\n"
        "    Amount\n"
        "FROM [lib://Data/Sales.qvd] (qvd);"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", QVD_FIELDS)
    assert result == ["Amount", "CustomerID", "OrderDate"]


# ---------------------------------------------------------------------------
# _split_field_list
# ---------------------------------------------------------------------------

def test_split_field_list_basic():
    result = qlik_mcp._split_field_list("CustomerID, OrderDate, Amount")
    assert result == ["CustomerID", "OrderDate", "Amount"]


def test_split_field_list_nested_parens():
    result = qlik_mcp._split_field_list("Year(OrderDate), Amount, Left(Name, 10)")
    assert result == ["Year(OrderDate)", "Amount", "Left(Name, 10)"]


def test_split_field_list_empty_input():
    result = qlik_mcp._split_field_list("   ")
    assert result == []


# ---------------------------------------------------------------------------
# _extract_field_from_expression
# ---------------------------------------------------------------------------

def test_extract_plain_field():
    assert qlik_mcp._extract_field_from_expression("CustomerID") == "CustomerID"


def test_extract_bracket_quoted_field():
    assert qlik_mcp._extract_field_from_expression("[Order Date]") == "Order Date"


def test_extract_function_wrapped_field():
    assert qlik_mcp._extract_field_from_expression("Year(OrderDate)") == "OrderDate"


def test_extract_multi_arg_function():
    assert qlik_mcp._extract_field_from_expression("Left(CustomerName, 10)") == "CustomerName"


def test_extract_empty_returns_none():
    assert qlik_mcp._extract_field_from_expression("") is None


# ---------------------------------------------------------------------------
# _fetch_app_script
# ---------------------------------------------------------------------------

def test_fetch_app_script_returns_script_text():
    versions = [{"id": "v1", "createdAt": "2024-01-01T00:00:00Z"}]
    script_data = {"script": "LOAD * FROM [lib://Data/Sales.qvd] (qvd);"}

    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [versions, script_data]
            return await qlik_mcp._fetch_app_script("app-123")

    result = asyncio.run(run())
    assert result == "LOAD * FROM [lib://Data/Sales.qvd] (qvd);"


def test_fetch_app_script_returns_none_on_error():
    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("Connection error")
            return await qlik_mcp._fetch_app_script("app-123")

    result = asyncio.run(run())
    assert result is None


def test_fetch_app_script_returns_none_when_no_versions():
    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = []
            return await qlik_mcp._fetch_app_script("app-123")

    result = asyncio.run(run())
    assert result is None


# ---------------------------------------------------------------------------
# qlik_get_qvd_field_usage — note logic integration tests
# ---------------------------------------------------------------------------

def test_field_usage_script_unavailable_note():
    """App where _fetch_app_script returns None → note: script_unavailable."""
    ds_data = {
        "schema": {
            "dataFields": [
                {"name": "CustomerID"},
                {"name": "OrderDate"},
            ]
        }
    }

    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = ds_data
            with patch.object(qlik_mcp, "_fetch_app_script", new_callable=AsyncMock) as mock_script:
                mock_script.return_value = None
                params = qlik_mcp.GetQvdFieldUsageInput(
                    qvd_qri="qri:datafile:dsg://t/s/Sales.qvd",
                    dataset_id="ds-1",
                    app_qris=["qri:app:sense://app-abc"],
                )
                return await qlik_mcp.qlik_get_qvd_field_usage(params)

    result = json.loads(asyncio.run(run()))
    app_data = result["per_app"]["qri:app:sense://app-abc"]
    assert app_data["note"] == "script_unavailable"
    assert app_data["fields"] == []


def test_field_usage_qvd_not_referenced_note():
    """App whose script doesn't reference the QVD → note: qvd_not_referenced."""
    ds_data = {
        "schema": {
            "dataFields": [{"name": "CustomerID"}, {"name": "OrderDate"}]
        }
    }

    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = ds_data
            with patch.object(qlik_mcp, "_fetch_app_script", new_callable=AsyncMock) as mock_script:
                # Script that references a completely different QVD
                mock_script.return_value = "LOAD x FROM [lib://Other.qvd] (qvd);"
                params = qlik_mcp.GetQvdFieldUsageInput(
                    qvd_qri="qri:datafile:dsg://t/s/Sales.qvd",
                    dataset_id="ds-1",
                    app_qris=["qri:app:sense://app-abc"],
                )
                return await qlik_mcp.qlik_get_qvd_field_usage(params)

    result = json.loads(asyncio.run(run()))
    app_data = result["per_app"]["qri:app:sense://app-abc"]
    assert app_data["note"] == "qvd_not_referenced"
    assert app_data["fields"] == []


def test_field_usage_fields_found_note_is_null():
    """App that references QVD with schema fields → note: null, fields populated."""
    ds_data = {
        "schema": {
            "dataFields": [{"name": "CustomerID"}, {"name": "OrderDate"}]
        }
    }

    async def run():
        with patch.object(qlik_mcp, "_qlik_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = ds_data
            with patch.object(qlik_mcp, "_fetch_app_script", new_callable=AsyncMock) as mock_script:
                mock_script.return_value = "LOAD CustomerID, OrderDate FROM [lib://Data/Sales.qvd] (qvd);"
                params = qlik_mcp.GetQvdFieldUsageInput(
                    qvd_qri="qri:datafile:dsg://t/s/Sales.qvd",
                    dataset_id="ds-1",
                    app_qris=["qri:app:sense://app-abc"],
                )
                return await qlik_mcp.qlik_get_qvd_field_usage(params)

    result = json.loads(asyncio.run(run()))
    app_data = result["per_app"]["qri:app:sense://app-abc"]
    assert app_data["note"] is None
    assert app_data["fields"] == ["CustomerID", "OrderDate"]
