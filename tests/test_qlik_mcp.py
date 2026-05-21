"""Unit tests for qlik_mcp pure helper functions."""
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


def test_parse_no_matching_qvd_returns_empty():
    script = "LOAD CustomerID FROM [lib://Data/Orders.qvd] (qvd);"
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
