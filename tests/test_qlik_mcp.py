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
# _strip_script_comments
# ---------------------------------------------------------------------------

def test_strip_block_comment_basic():
    result = qlik_mcp._strip_script_comments("before /* comment */ after")
    assert "comment" not in result
    assert "before" in result
    assert "after" in result


def test_strip_block_comment_multiline():
    result = qlik_mcp._strip_script_comments("A,\n/* old expr\n  AS X,*/\nB")
    assert "old expr" not in result
    assert "A," in result
    assert "B" in result


def test_strip_line_comment():
    result = qlik_mcp._strip_script_comments("FieldA, // this is a comment\nFieldB")
    assert "this is a comment" not in result
    assert "FieldA" in result
    assert "FieldB" in result


def test_strip_line_comment_preserves_newline():
    """Newline after // comment must remain so subsequent lines stay separate."""
    result = qlik_mcp._strip_script_comments("A, // comment\nB")
    assert "\n" in result


def test_strip_block_comment_with_trailing_comma():
    """Reproduce the real-world bug: field after `,*/ FIELD` must survive."""
    text = "    DATAENTRADA,\n    /*\n    old AS DATAENTRADA,*/\n    CODALMOX_ORIGEM,"
    result = qlik_mcp._strip_script_comments(text)
    assert "CODALMOX_ORIGEM" in result
    assert "old AS DATAENTRADA" not in result


def test_parse_field_after_block_comment():
    """Field immediately following a block comment ending with ,*/ must be found."""
    schema = ["Hotel", "DATAENTRADA", "CODALMOX_ORIGEM", "STATUS"]
    script = (
        "LOAD\n"
        "    Hotel,\n"
        "    DATE(FLOOR(DATAENTRADA), 'DD/MM/YYYY') AS DATAENTRADA,\n"
        "    //Date#(left(DATAENTRADA, 10), 'DD/MM/YYYY')\n"
        "    /*\n"
        "    If(Hotel='X',\n"
        "          Date#(left(DATAENTRADA, 10), 'DD/MM/YYYY')\n"
        "        , Date#(left(DATE(DATAENTRADA, 'DD/MM/YYYY'), 10), 'DD/MM/YYYY')\n"
        "      )                                             AS DATAENTRADA,*/\n"
        "    CODALMOX_ORIGEM                                            ,\n"
        "    STATUS\n"
        "FROM [lib://Data/Sales.qvd] (qvd);\n"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", schema)
    assert result is not None
    assert "CODALMOX_ORIGEM" in result
    assert "STATUS" in result
    assert "Hotel" in result
    assert "DATAENTRADA" in result


# ---------------------------------------------------------------------------
# _extract_identifiers_from_expression
# ---------------------------------------------------------------------------

SCHEMA = {"CustomerID", "OrderDate", "Amount", "Region", "Status", "Hotel",
          "NCONTROLE", "CODALMOX", "MES", "ANO"}


def test_identifiers_plain_field():
    result = qlik_mcp._extract_identifiers_from_expression("CustomerID", SCHEMA)
    assert result == {"CustomerID"}


def test_identifiers_string_literal_not_matched():
    """String literals like 'E' must not be confused with a field named E."""
    schema = {"E", "CustomerID"}
    result = qlik_mcp._extract_identifiers_from_expression("CustomerID & 'E' & 'x'", schema)
    assert "CustomerID" in result
    assert "E" not in result


def test_identifiers_concatenation():
    """All identifiers inside a & concatenation must be found."""
    expr = "TRIM(NCONTROLE & 'E' & CODALMOX & MES & ANO & Hotel)"
    result = qlik_mcp._extract_identifiers_from_expression(expr, SCHEMA)
    assert result == {"NCONTROLE", "CODALMOX", "MES", "ANO", "Hotel"}


def test_identifiers_arithmetic():
    result = qlik_mcp._extract_identifiers_from_expression(
        "Amount * 1.1 + Region", {"Amount", "Region"}
    )
    assert result == {"Amount", "Region"}


def test_identifiers_bracket_quoted():
    result = qlik_mcp._extract_identifiers_from_expression(
        "[Order Date] + Amount", {"Order Date", "Amount"}
    )
    assert result == {"Order Date", "Amount"}


def test_identifiers_unknown_tokens_ignored():
    result = qlik_mcp._extract_identifiers_from_expression(
        "TRIM(Unknown1 & Unknown2)", SCHEMA
    )
    assert result == set()


def test_parse_concatenation_expression():
    """Fields inside & concatenation must all be reported."""
    schema = ["NCONTROLE", "CODALMOX", "MES", "ANO", "Hotel", "STATUS"]
    script = (
        "LOAD\n"
        "    TRIM(NCONTROLE & 'E' & CODALMOX & MES & ANO & Hotel) AS NCONTROLE_ENTRADA,\n"
        "    STATUS\n"
        "FROM [lib://Data/Sales.qvd] (qvd);\n"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", schema)
    assert result == ["ANO", "CODALMOX", "Hotel", "MES", "NCONTROLE", "STATUS"]


def test_parse_where_clause_fields():
    """Fields referenced only in a WHERE clause must be included."""
    schema = ["CustomerID", "OrderDate", "Status"]
    script = (
        "LOAD CustomerID, OrderDate\n"
        "FROM [lib://Data/Sales.qvd] (qvd)\n"
        "WHERE Status = 'Active';\n"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", schema)
    assert result is not None
    assert "CustomerID" in result
    assert "OrderDate" in result
    assert "Status" in result


def test_parse_if_expression_both_branches():
    """Both branches of an If() expression must be reported."""
    schema = ["Hotel", "FieldA", "FieldB", "Result"]
    script = (
        "LOAD If(Hotel = 'X', FieldA, FieldB) AS Result\n"
        "FROM [lib://Data/Sales.qvd] (qvd);\n"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "Sales", schema)
    assert result is not None
    assert "Hotel" in result
    assert "FieldA" in result
    assert "FieldB" in result


def test_parse_left_join_load():
    """LEFT JOIN LOAD pattern (real-world Vendas script) must work end-to-end."""
    schema = ["NCONTROLE", "CODALMOX", "MES", "ANO", "Hotel",
              "TRANSACAO", "TIPOTRANSACAO", "STATUS", "DATAENTRADA"]
    script = (
        "LEFT JOIN\n"
        "LOAD\n"
        "    TRIM(NCONTROLE & 'E' & CODALMOX & MES & ANO & Hotel) AS NCONTROLE_ENTRADA,\n"
        "    TRANSACAO,\n"
        "    TIPOTRANSACAO,\n"
        "    STATUS,\n"
        "    DATE(FLOOR(DATAENTRADA), 'DD/MM/YYYY') AS DATAENTRADA\n"
        "FROM [lib://Data/SEI_ENTRADAS.qvd] (qvd);\n"
    )
    result = qlik_mcp._parse_qvd_fields_from_script(script, "SEI_ENTRADAS", schema)
    assert result == sorted(schema)


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
