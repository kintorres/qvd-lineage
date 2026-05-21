# Script-Based QVD Field Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken data-model intersection in `qlik_get_qvd_field_usage` with load script parsing that correctly handles renamed fields, expressions, and dropped fields.

**Architecture:** Two new private helpers are added to `qlik_mcp.py`: a pure parser (`_parse_qvd_fields_from_script` and sub-helpers) and an async API fetcher (`_fetch_app_script`). The tool's interface, parameters, and JSON return format are unchanged. Unit tests go in `tests/test_qlik_mcp.py`.

**Tech Stack:** Python 3.10+, `re` (stdlib), `pytest`, existing `httpx`/FastMCP stack

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `qlik_mcp.py` | Add `import re`; add 4 pure helpers + 1 async helper; rewrite tool 4 internals + docstring |
| Create | `tests/test_qlik_mcp.py` | Unit tests for pure helpers and `_fetch_app_script` |
| Modify | `requirements.txt` | Add `pytest>=7.0` (test dependency) |

---

### Task 1: Add pytest and create tests for pure parsing helpers

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_qlik_mcp.py`

- [ ] **Step 1: Add pytest to requirements.txt**

Replace the entire file with:
```
mcp[cli]>=1.0.0
httpx>=0.27.0
pydantic>=2.0
pytest>=7.0
pytest-asyncio>=0.23
```

- [ ] **Step 2: Install**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && pip install pytest pytest-asyncio
```
Expected: installed successfully

- [ ] **Step 3: Create tests directory and empty __init__.py**

```bash
mkdir -p "/Users/kintorres/Documents/QVD Lineage/tests" && touch "/Users/kintorres/Documents/QVD Lineage/tests/__init__.py"
```

- [ ] **Step 4: Write the failing tests**

Create `tests/test_qlik_mcp.py` with exactly this content:

```python
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
```

- [ ] **Step 5: Run tests to confirm they fail (functions not yet defined)**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m pytest tests/test_qlik_mcp.py -v 2>&1 | head -30
```
Expected: `AttributeError: module 'qlik_mcp' has no attribute '_extract_qvd_name_from_qri'`

- [ ] **Step 6: Commit the failing tests**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && git add requirements.txt tests/ && git commit -m "add failing tests for script-parsing helpers"
```

---

### Task 2: Implement pure parsing helpers

**Files:**
- Modify: `qlik_mcp.py` — add `import re` and 4 pure helper functions after `_handle_api_error`

- [ ] **Step 1: Add `import re` to the imports section**

In `qlik_mcp.py`, find and replace:
```python
import json
import os
```
With:
```python
import json
import os
import re
```

- [ ] **Step 2: Add the four pure helpers after `_handle_api_error`**

Find the exact string:
```python
# ---------------------------------------------------------------------------
# Tool 1 — Search QVD datasets
# ---------------------------------------------------------------------------
```
And insert the following block immediately before it:

```python
# ---------------------------------------------------------------------------
# Script parsing helpers (pure functions — no API calls)
# ---------------------------------------------------------------------------

def _extract_qvd_name_from_qri(qvd_qri: str) -> str:
    """Extract a searchable QVD filename (without extension) from a QRI string.

    Examples:
        'qri:datafile:dsg://tenant/space/Sales_Data.qvd' -> 'Sales_Data'
        'qri:datafile:dsg://tenant/space/Orders'         -> 'Orders'
    """
    parts = re.split(r"[/\\]", qvd_qri)
    last = parts[-1] if parts else qvd_qri
    return re.sub(r"\.qvd$", "", last, flags=re.IGNORECASE).strip() or qvd_qri


def _resolve_variables(script: str) -> str:
    """Extract SET/LET variable definitions and substitute $(varName) references.

    Performs up to 5 substitution passes to handle nested variables such as
    SET vFull = '$(vBase)$(vFile).qvd' where vBase and vFile are also defined.
    """
    var_re = re.compile(
        r"\b(?:SET|LET)\s+(\w+)\s*=\s*'?([^';\n]+?)'?\s*;",
        re.IGNORECASE,
    )
    variables: dict[str, str] = {
        m.group(1): m.group(2).strip()
        for m in var_re.finditer(script)
    }
    resolved = script
    for _ in range(5):
        prev = resolved
        for name, value in variables.items():
            resolved = re.sub(
                r"\$\(" + re.escape(name) + r"\)",
                value,
                resolved,
                flags=re.IGNORECASE,
            )
        if resolved == prev:
            break
    return resolved


def _split_field_list(field_list: str) -> list[str]:
    """Split a Qlik field list by top-level commas, respecting parentheses nesting.

    Example:
        'CustomerID, Year(OrderDate) AS Yr, Amount' ->
        ['CustomerID', ' Year(OrderDate) AS Yr', ' Amount']
    """
    tokens: list[str] = []
    depth = 0
    current: list[str] = []
    for char in field_list:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current).strip())
    return tokens


def _extract_field_from_expression(expr: str) -> str | None:
    """Extract the source field name from a Qlik field expression.

    Handles plain names, bracket-quoted names, and function calls by
    recursively unwrapping the outermost function to reach the first argument.

    Examples:
        'OrderDate'              -> 'OrderDate'
        '[Order Date]'           -> 'Order Date'
        'Year(OrderDate)'        -> 'OrderDate'
        'Left(CustomerName, 10)' -> 'CustomerName'
    """
    expr = expr.strip().strip(";")
    if not expr:
        return None
    # Bracket-quoted field: [Field Name] -> Field Name
    bracket = re.match(r"^\[(.+)\]$", expr)
    if bracket:
        return bracket.group(1)
    # No parentheses: plain field name (strip surrounding quotes)
    if "(" not in expr:
        return expr.strip("\"'") or None
    # Function call: unwrap outermost function and recurse on first argument
    func = re.match(r"^\w+\s*\((.+)\)$", expr, re.DOTALL)
    if func:
        first_arg = _split_field_list(func.group(1))[0].strip() if func.group(1) else ""
        return _extract_field_from_expression(first_arg) if first_arg else None
    return None


def _parse_qvd_fields_from_script(
    script: str,
    qvd_name: str,
    all_qvd_fields: list[str],
) -> list[str]:
    """Return QVD fields referenced in LOAD statements that read from qvd_name.

    Steps:
      1. Resolve SET/LET variables to expand $(var) references in FROM paths.
      2. Find every LOAD...FROM [...qvd_name...qvd] block.
      3. Parse the field list: LOAD * returns all fields; otherwise extract
         source field names (before AS, unwrapping function calls).
      4. Return only fields that exist in all_qvd_fields, deduplicated and sorted.

    Args:
        script:         Full Qlik load script text.
        qvd_name:       QVD filename without extension (case-insensitive match).
        all_qvd_fields: Complete list of field names from the QVD schema.

    Returns:
        Sorted list of QVD field names referenced in matching LOAD blocks.
        Returns all_qvd_fields if any matching block uses LOAD *.
        Returns [] if no matching LOAD block is found.
    """
    qvd_field_set = set(all_qvd_fields)
    resolved = _resolve_variables(script)

    # Match: LOAD <fields> FROM [path/name.qvd] (qvd)
    # The field list and path may span multiple lines.
    load_from_re = re.compile(
        r"\bLOAD\b(.*?)\bFROM\b\s*\[?([^\]\n;]+?\.qvd[^\]\n;]*?)\]?\s*\(qvd\)",
        re.IGNORECASE | re.DOTALL,
    )

    found_fields: set[str] = set()

    for match in load_from_re.finditer(resolved):
        fields_str = match.group(1).strip()
        from_path = match.group(2).strip()

        # Check whether this FROM path references the target QVD
        fname = re.split(r"[/\\]", from_path)[-1]
        fname_no_ext = re.sub(r"\.qvd$", "", fname, flags=re.IGNORECASE).strip()
        if qvd_name.lower() not in fname_no_ext.lower():
            continue

        # LOAD * → every QVD field is used
        if fields_str.strip() == "*":
            return sorted(all_qvd_fields)

        # Parse comma-separated field expressions
        for token in _split_field_list(fields_str):
            token = token.strip()
            if not token:
                continue
            # Source is the part before AS
            source = re.split(r"\bAS\b", token, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            field = _extract_field_from_expression(source)
            if field and field in qvd_field_set:
                found_fields.add(field)

    return sorted(found_fields)


```

- [ ] **Step 3: Run the pure-function tests**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m pytest tests/test_qlik_mcp.py -v -k "not fetch_app" 2>&1
```
Expected: all pure-function tests PASS

- [ ] **Step 4: Verify syntax**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m py_compile qlik_mcp.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && git add qlik_mcp.py && git commit -m "add pure script-parsing helpers"
```

---

### Task 3: Add `_fetch_app_script` async helper

**Files:**
- Modify: `qlik_mcp.py` — insert async helper inside the script parsing section

- [ ] **Step 1: Add `_fetch_app_script` at the end of the script parsing helpers section**

Find the exact string:
```python
# ---------------------------------------------------------------------------
# Tool 1 — Search QVD datasets
# ---------------------------------------------------------------------------
```
And insert the following block immediately before it (after the closing of `_parse_qvd_fields_from_script`):

```python
async def _fetch_app_script(app_id: str) -> str | None:
    """Fetch the latest load script text for a Qlik app.

    Calls GET /api/v1/apps/{app_id}/scripts to list versions, picks the most
    recent, then calls GET /api/v1/apps/{app_id}/scripts/{id} for the content.

    Returns:
        Script text as a string, or None if the script cannot be fetched
        (e.g. permission error, app not found, empty version list).
    """
    try:
        versions_resp = await _qlik_request(f"api/v1/apps/{app_id}/scripts")
        version_list: list = (
            versions_resp
            if isinstance(versions_resp, list)
            else versions_resp.get("data", [])
        )
        if not version_list:
            return None

        # Sort descending by createdAt; fall back to list order if key is absent
        try:
            version_list = sorted(
                version_list,
                key=lambda v: v.get("createdAt", ""),
                reverse=True,
            )
        except Exception:
            pass

        script_id = version_list[0].get("id")
        if not script_id:
            return None

        script_data = await _qlik_request(
            f"api/v1/apps/{app_id}/scripts/{script_id}"
        )
        text = (
            script_data.get("script")
            or script_data.get("content")
            or script_data.get("data")
        )
        return text if isinstance(text, str) else None

    except Exception:
        return None


```

- [ ] **Step 2: Run the fetch_app_script tests**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m pytest tests/test_qlik_mcp.py -v -k "fetch_app" 2>&1
```
Expected: all 3 `fetch_app` tests PASS

- [ ] **Step 3: Run all tests**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m pytest tests/test_qlik_mcp.py -v 2>&1
```
Expected: all tests PASS

- [ ] **Step 4: Verify syntax**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m py_compile qlik_mcp.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && git add qlik_mcp.py && git commit -m "add _fetch_app_script async helper"
```

---

### Task 4: Replace `qlik_get_qvd_field_usage` internals

**Files:**
- Modify: `qlik_mcp.py` — replace docstring + body of `qlik_get_qvd_field_usage`

- [ ] **Step 1: Replace the docstring**

Find and replace exactly:
```python
    """Identify which QVD fields are used by each app and which are never used.

    Internal flow:
      1. Fetch all QVD fields via GET /api/v1/data-sets/{dataset_id}
      2. For each app, call GET /api/v1/apps/{appId}/data/metadata and intersect
         the data model fields with the QVD schema
      3. Consolidate: fields used in at least one app vs fields never used

    Args:
        params (GetQvdFieldUsageInput):
            - qvd_qri (str): QRI of the base QVD (secureQri from qlik_search_qvd).
            - dataset_id (str): resourceId of the QVD (from qlik_search_qvd).
            - app_qris (list[str]): QRIs of the apps to analyze (from qlik_get_qvd_impact).

    Returns:
        str: JSON-formatted string with consolidated analysis:
            {
                "qvd_qri": str,
                "total_qvd_fields": int,
                "apps_analyzed": int,
                "fields_used": [
                    {"field": str, "used_in_apps": [str]}
                ],
                "fields_unused": [str],
                "per_app": {
                    "app_qri": {"fields": [str], "field_count": int}
                }
            }
        Or "Error: <message>" on failure.
    """
```
With:
```python
    """Identify which QVD fields are used by each app and which are never used.

    Internal flow:
      1. Fetch all QVD fields via GET /api/v1/data-sets/{dataset_id}
      2. For each app, fetch its load script via GET /api/v1/apps/{appId}/scripts
         and parse it to find which QVD fields are referenced — including fields
         that are renamed (AS), used inside expressions, or later dropped from
         the data model
      3. Consolidate: fields referenced in at least one app vs fields never used

    Args:
        params (GetQvdFieldUsageInput):
            - qvd_qri (str): QRI of the base QVD (secureQri from qlik_search_qvd).
            - dataset_id (str): resourceId of the QVD (from qlik_search_qvd).
            - app_qris (list[str]): QRIs of the apps to analyze (from qlik_get_qvd_impact).

    Returns:
        str: JSON-formatted string with consolidated analysis:
            {
                "qvd_qri": str,
                "total_qvd_fields": int,
                "apps_analyzed": int,
                "fields_used": [
                    {"field": str, "used_in_apps": [str]}
                ],
                "fields_unused": [str],
                "per_app": {
                    "app_qri": {
                        "fields": [str],
                        "field_count": int,
                        "note": str | null   # "script_unavailable" or "qvd_not_referenced"
                    }
                }
            }
        Or "Error: <message>" on failure.
    """
```

- [ ] **Step 2: Replace the function body**

Find and replace exactly:
```python
    try:
        # ── Step 1: get all QVD fields from data-sets API ──────────────────
        all_qvd_fields: list[str] = []
        try:
            ds_data = await _qlik_request(f"api/v1/data-sets/{params.dataset_id}")
            data_fields = ds_data.get("schema", {}).get("dataFields", [])
            all_qvd_fields = [f.get("name") for f in data_fields if f.get("name")]
        except Exception:
            pass  # will fall back to fields discovered via app metadata

        # ── Step 2: per-app field usage via app data model metadata ────────
        # GET /api/v1/apps/{appId}/data/metadata returns all fields in the
        # app's in-memory data model. Intersecting with QVD fields gives us
        # exactly which QVD fields each app actually loads.
        per_app: dict[str, list[str]] = {}
        qvd_field_set = set(all_qvd_fields)

        for app_qri in params.app_qris:
            app_id = app_qri.replace("qri:app:sense://", "")
            fields_for_app: list[str] = []

            try:
                meta = await _qlik_request(f"api/v1/apps/{app_id}/data/metadata")
                app_fields_raw = meta.get("fields", [])
                # Keep only fields whose name appears in the QVD schema
                for f in app_fields_raw:
                    name = f.get("name") or f.get("fieldName")
                    if name and name in qvd_field_set:
                        fields_for_app.append(name)
            except Exception:
                pass

            per_app[app_qri] = sorted(set(fields_for_app))

        # ── Step 3: consolidate ─────────────────────────────────────────────
        all_used: dict[str, list[str]] = {}
        for app_qri, fields in per_app.items():
            for f in fields:
                all_used.setdefault(f, []).append(app_qri)

        # Merge: if app metadata found fields not in schema, add them
        known = set(all_qvd_fields)
        for f in all_used:
            if f not in known:
                all_qvd_fields.append(f)

        fields_unused = sorted(f for f in all_qvd_fields if f not in all_used)

        result = {
            "qvd_qri": params.qvd_qri,
            "total_qvd_fields": len(all_qvd_fields),
            "apps_analyzed": len(params.app_qris),
            "fields_used": [
                {"field": f, "used_in_apps": apps}
                for f, apps in sorted(all_used.items())
            ],
            "fields_unused": fields_unused,
            "per_app": {
                app_qri: {"fields": fields, "field_count": len(fields)}
                for app_qri, fields in per_app.items()
            },
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return _handle_api_error(e)
```
With:
```python
    try:
        # ── Step 1: fetch all QVD fields from the data-sets API ───────────
        ds_data = await _qlik_request(f"api/v1/data-sets/{params.dataset_id}")
        data_fields = ds_data.get("schema", {}).get("dataFields", [])
        all_qvd_fields = [f.get("name") for f in data_fields if f.get("name")]
        if not all_qvd_fields:
            return f"Error: No fields found for dataset {params.dataset_id}. Verify the dataset_id."

        # Derive the QVD filename (without extension) for script matching
        qvd_name = _extract_qvd_name_from_qri(params.qvd_qri)

        # ── Step 2: per-app field usage via load script parsing ───────────
        per_app: dict[str, dict] = {}

        for app_qri in params.app_qris:
            app_id = app_qri.replace("qri:app:sense://", "")

            script = await _fetch_app_script(app_id)

            if script is None:
                per_app[app_qri] = {
                    "fields": [],
                    "field_count": 0,
                    "note": "script_unavailable",
                }
                continue

            fields = _parse_qvd_fields_from_script(script, qvd_name, all_qvd_fields)
            per_app[app_qri] = {
                "fields": fields,
                "field_count": len(fields),
                "note": None if fields else "qvd_not_referenced",
            }

        # ── Step 3: consolidate ───────────────────────────────────────────
        all_used: dict[str, list[str]] = {}
        for app_qri, app_data in per_app.items():
            for f in app_data["fields"]:
                all_used.setdefault(f, []).append(app_qri)

        fields_unused = sorted(f for f in all_qvd_fields if f not in all_used)

        result = {
            "qvd_qri": params.qvd_qri,
            "total_qvd_fields": len(all_qvd_fields),
            "apps_analyzed": len(params.app_qris),
            "fields_used": [
                {"field": f, "used_in_apps": apps}
                for f, apps in sorted(all_used.items())
            ],
            "fields_unused": fields_unused,
            "per_app": per_app,
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return _handle_api_error(e)
```

- [ ] **Step 3: Run all tests**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m pytest tests/test_qlik_mcp.py -v 2>&1
```
Expected: all tests PASS

- [ ] **Step 4: Verify syntax**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && python3 -m py_compile qlik_mcp.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 5: Commit and push**

```bash
cd "/Users/kintorres/Documents/QVD Lineage" && git add qlik_mcp.py && git commit -m "replace data-model intersection with load script parsing in qlik_get_qvd_field_usage" && git push
```

---

## Self-Review

**Spec coverage:**
- ✅ `_fetch_app_script(app_id)` — Task 3
- ✅ `_parse_qvd_fields_from_script(script, qvd_name, all_qvd_fields)` — Task 2
- ✅ Variable resolution (SET/LET + multi-pass $(var) substitution) — Task 2, `_resolve_variables`
- ✅ LOAD block matching with QVD name check — Task 2, `_parse_qvd_fields_from_script`
- ✅ `LOAD *` returns all fields — Task 2 + test
- ✅ Field rename (`AS`) handled — Task 2 + test
- ✅ Expression unwrapping (`Year(OrderDate)`) — Task 2 + test
- ✅ `script_unavailable` note — Task 4
- ✅ `qvd_not_referenced` note — Task 4
- ✅ QVD schema failure returns error immediately — Task 4 (`if not all_qvd_fields`)
- ✅ Tool interface, parameters, return format unchanged — Task 4

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `_parse_qvd_fields_from_script` returns `list[str]` — matches usage in Task 4 ✅
- `_fetch_app_script` returns `str | None` — `None` check in Task 4 ✅
- `per_app` dict values changed from `list[str]` to `dict` — Task 4 builds them as dicts ✅
- `_extract_qvd_name_from_qri` used in Task 4 — defined in Task 2 ✅
