#!/usr/bin/env python3
"""
MCP Server for Qlik Cloud REST API.
Provides tools for QVD lineage analysis and field-level usage across apps.

Environment variables required:
    QLIK_BASE_URL  - Tenant URL (e.g., https://your-tenant.us.qlikcloud.com)
    QLIK_API_KEY   - API key generated from the Qlik Cloud Management Console
"""

import json
import os
import re
from typing import Optional
from urllib.parse import quote
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("qlik_mcp")

QLIK_BASE_URL = os.getenv("QLIK_BASE_URL", "").rstrip("/")
QLIK_API_KEY = os.getenv("QLIK_API_KEY", "")


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

async def _qlik_request(
    endpoint: str,
    params: dict | None = None,
    raw_params: str | None = None,
) -> dict | list:
    """Authenticated GET request against the Qlik Cloud REST API.

    Args:
        endpoint:   API path (e.g. 'api/v1/items')
        params:     Query params dict — values are URL-encoded by httpx (safe for most cases)
        raw_params: Pre-built query string appended verbatim, useful when the Qlik API
                    requires literal bracket syntax such as 'resourceType=dataset[qvd]'
                    that httpx would otherwise encode as 'dataset%5Bqvd%5D'.
    """
    if not QLIK_BASE_URL or not QLIK_API_KEY:
        raise ValueError(
            "QLIK_BASE_URL and QLIK_API_KEY environment variables must be set. "
            "QLIK_BASE_URL should be your tenant URL "
            "(e.g., https://your-tenant.us.qlikcloud.com) and "
            "QLIK_API_KEY your API key from the Management Console."
        )

    headers = {
        "Authorization": f"Bearer {QLIK_API_KEY}",
        "Accept": "application/json",
    }

    url = f"{QLIK_BASE_URL}/{endpoint.lstrip('/')}"
    if raw_params:
        url = f"{url}?{raw_params}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
            params=params if not raw_params else None,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


def _handle_api_error(e: Exception) -> str:
    """Return a clear, actionable error string for any exception."""
    if isinstance(e, ValueError):
        return f"Configuration error: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        messages = {
            401: "Unauthorized. Verify your QLIK_API_KEY environment variable.",
            403: "Forbidden. Your API key may not have permission to access this resource.",
            404: "Resource not found. Verify the IDs or QRI provided.",
            429: "Rate limit exceeded. Wait before making more requests.",
        }
        if status in messages:
            return f"Error: {messages[status]}"
        try:
            body = e.response.json()
            return f"Error: API request failed with status {status}: {json.dumps(body, indent=2)}"
        except Exception:
            return f"Error: API request failed with status {status}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. The Qlik API may be temporarily unavailable."
    if isinstance(e, httpx.ConnectError):
        return "Error: Could not connect to Qlik. Verify your QLIK_BASE_URL environment variable."
    return f"Error: Unexpected error: {type(e).__name__}: {e}"


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
    # Two alternatives: single-quoted value or bare (unquoted) value.
    # Using alternation avoids the lazy-quantifier truncation that occurs
    # when trailing quote and semicolon are both optional.
    var_re = re.compile(
        r"\b(?:SET|LET)\s+(\w+)\s*=\s*(?:'([^'\n]*)'|([^';\n]+))\s*;?",
        re.IGNORECASE,
    )
    variables: dict[str, str] = {
        m.group(1): (m.group(2) if m.group(2) is not None else m.group(3)).strip()
        for m in var_re.finditer(script)
    }
    resolved = script
    for _ in range(5):
        prev = resolved
        for name, value in variables.items():
            resolved = re.sub(
                r"\$\(" + re.escape(name) + r"\)",
                lambda _: value,
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
    return [t for t in tokens if t]


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
) -> list[str] | None:
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
        None if no LOAD block references qvd_name in this script.
        Sorted list of QVD field names referenced in matching LOAD blocks
        (may be empty if a LOAD block was found but no fields matched the schema).
        Returns all_qvd_fields if any matching block uses LOAD *.
    """
    qvd_field_set = set(all_qvd_fields)
    resolved = _resolve_variables(script)

    # Match: LOAD <fields> FROM [path/name.qvd] (qvd)
    # The field list and path may span multiple lines.
    load_from_re = re.compile(
        r"\bLOAD\b([^;]*?)\bFROM\b\s*\[?([^\]\n;]+?\.qvd[^\]\n;]*?)\]?\s*\(qvd\)",
        re.IGNORECASE | re.DOTALL,
    )

    found_fields: set[str] = set()
    found_block = False

    for match in load_from_re.finditer(resolved):
        fields_str = match.group(1).strip()
        from_path = match.group(2).strip()

        # Check whether this FROM path references the target QVD
        fname = re.split(r"[/\\]", from_path)[-1]
        fname_no_ext = re.sub(r"\.qvd$", "", fname, flags=re.IGNORECASE).strip()
        if qvd_name.lower() not in fname_no_ext.lower():
            continue

        found_block = True

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

    if not found_block:
        return None
    return sorted(found_fields)


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


# ---------------------------------------------------------------------------
# Tool 1 — Search QVD datasets
# ---------------------------------------------------------------------------

class SearchQvdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    qvd_name: str = Field(
        ...,
        description="Name or partial name of the QVD to search for (e.g., 'Sales', 'Orders_2024')",
        min_length=1,
        max_length=500,
    )
    limit: Optional[int] = Field(
        default=20,
        description="Maximum number of results to return (1–100)",
        ge=1,
        le=100,
    )


@mcp.tool(
    name="qlik_search_qvd",
    annotations={
        "title": "Search Qlik QVD Datasets",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qlik_search_qvd(params: SearchQvdInput) -> str:
    """Search for QVD dataset files in the Qlik Cloud item catalog.

    Single call that returns BOTH identifiers needed for the full pipeline:
      - resourceId  → used as dataset_id in qlik_get_qvd_field_usage
      - secureQri   → used as qvd_qri in qlik_get_qvd_impact and qlik_get_qvd_field_usage

    Queries /api/v1/items?resourceType=dataset[qix-df,qvd]&query=...
    (subtypes qix-df for Data Space QVDs, qvd for catalog-published ones).

    Args:
        params (SearchQvdInput):
            - qvd_name (str): Search term to match against dataset names.
            - limit (Optional[int]): Max results (default 20, max 100).

    Returns:
        str: JSON-formatted string:
            {
                "total": int,
                "count": int,
                "items": [
                    {
                        "id": str,            # Catalog item ID
                        "name": str,          # QVD display name
                        "resourceId": str,    # Use as dataset_id in qlik_get_qvd_field_usage
                        "secureQri": str,     # Use as qvd_qri in qlik_get_qvd_impact and qlik_get_qvd_field_usage
                        "resourceSubType": str,
                        "spaceId": str,
                        "createdAt": str,
                        "updatedAt": str
                    }
                ]
            }
        Or "No QVD datasets found matching '<qvd_name>'"
        Or "Error: <message>" on failure.

    Pipeline usage:
        1. qlik_search_qvd          → get resourceId + secureQri
        2. qlik_get_qvd_impact      → pass secureQri, get dependent app QRIs
        3. qlik_get_qvd_field_usage → pass secureQri + resourceId + app QRIs
    """
    try:
        # Brackets must be literal (not %5B%5D) — build raw query string manually.
        raw_params = "&".join([
            "resourceType=dataset[qix-df,qvd]",
            f"query={quote(params.qvd_name, safe='')}",
            f"limit={params.limit}",
        ])
        data = await _qlik_request("api/v1/items", raw_params=raw_params)

        items = data.get("data", [])
        total = data.get("meta", {}).get("count", len(items))

        if not items:
            return f"No QVD datasets found matching '{params.qvd_name}'"

        result = {
            "total": total,
            "count": len(items),
            "items": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "resourceId": item.get("resourceId"),
                    "secureQri": (
                        item.get("resourceAttributes", {}).get("secureQri")
                        or item.get("secureQri")
                    ),
                    "resourceSubType": item.get("resourceSubType"),
                    "spaceId": item.get("spaceId"),
                    "createdAt": item.get("createdAt"),
                    "updatedAt": item.get("updatedAt"),
                }
                for item in items
            ],
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return _handle_api_error(e)


# ---------------------------------------------------------------------------
# Tool 2 — QVD downstream impact / lineage
# ---------------------------------------------------------------------------

class GetQvdImpactInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    qvd_qri: str = Field(
        ...,
        description=(
            "QRI (Qlik Resource Identifier) of the QVD dataset. "
            "Obtained from the secureQri field returned by qlik_search_qvd."
        ),
        min_length=1,
    )
    down: Optional[int] = Field(
        default=1,
        description="Downstream depth to traverse in the impact graph (default 1, use -1 for unlimited)",
        ge=-1,
        le=20,
    )


@mcp.tool(
    name="qlik_get_qvd_impact",
    annotations={
        "title": "Get QVD Downstream Impact / Lineage",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qlik_get_qvd_impact(params: GetQvdImpactInput) -> str:
    """Identify which Qlik apps and resources depend on a given QVD dataset.

    Queries /api/v1/lineage-graphs/impact/{QVD_QRI}/overview?down=N to
    retrieve the downstream impact graph. Shows which apps, data models,
    or other assets consume the QVD, enabling change-impact analysis.

    Args:
        params (GetQvdImpactInput):
            - qvd_qri (str): QRI of the QVD (secureQri from qlik_search_qvd).
            - down (Optional[int]): Downstream depth to traverse (default 1).

    Returns:
        str: JSON-formatted string:
            {
                "qvd_qri": str,
                "nodes": [...],   # Resources that depend on this QVD
                "edges": [...],   # Relationships between those resources
                "summary": {
                    "total_nodes": int,
                    "total_edges": int
                }
            }
        Or "Error: <message>" on failure.

    Examples:
        - Direct consumers only → down=1 (default)
        - Two-level impact       → down=2
        - Use secureQri from qlik_search_qvd as qvd_qri
    """
    try:
        # QRI contains special chars (://, #) that must be percent-encoded in the path.
        # The '#' is especially critical — unencoded it becomes a URL fragment delimiter
        # and the server never receives the part after it.
        encoded_qri = quote(params.qvd_qri, safe="")
        raw_params = f"down={params.down}"
        data = await _qlik_request(
            f"api/v1/lineage-graphs/impact/{encoded_qri}/overview",
            raw_params=raw_params,
        )

        # The API wraps nodes/edges inside a "graph" object
        graph = data.get("graph", data)
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        metadata = graph.get("metadata", data.get("metadata", {}))

        result = {
            "qvd_qri": params.qvd_qri,
            "nodes": nodes,
            "edges": edges,
            "metadata": metadata,
            "summary": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            },
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return _handle_api_error(e)


# ---------------------------------------------------------------------------
# Tool 3 — Resolve app name from QRI or app ID
# ---------------------------------------------------------------------------

class GetAppNameInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    app_id: str = Field(
        ...,
        description="App GUID or full QRI (e.g. 'qri:app:sense://33148d98-...' or '33148d98-...')",
        min_length=1,
    )


@mcp.tool(
    name="qlik_get_app_name",
    annotations={
        "title": "Resolve Qlik App Name by ID or QRI",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qlik_get_app_name(params: GetAppNameInput) -> str:
    """Return the name, space, and metadata of a Qlik app by its ID or full QRI.

    Args:
        params (GetAppNameInput):
            - app_id (str): App GUID or full QRI (qri:app:sense://GUID).

    Returns:
        str: JSON-formatted string:
            {
                "id": str,
                "name": str,
                "spaceId": str,
                "ownerId": str,
                "createdAt": str,
                "updatedAt": str,
                "publishedAt": str | null
            }
        Or "Error: <message>" on failure.
    """
    try:
        # Extract GUID if provided as a full QRI
        app_id = params.app_id
        if app_id.startswith("qri:app:sense://"):
            app_id = app_id.replace("qri:app:sense://", "")

        data = await _qlik_request(f"api/v1/apps/{app_id}")
        attrs = data.get("attributes", data)

        result = {
            "id": attrs.get("id"),
            "name": attrs.get("name"),
            "spaceId": attrs.get("spaceId"),
            "ownerId": attrs.get("ownerId"),
            "createdAt": attrs.get("createdAt"),
            "updatedAt": attrs.get("updatedAt"),
            "publishedAt": attrs.get("publishedAt"),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return _handle_api_error(e)


# ---------------------------------------------------------------------------
# Tool 4 — Field-level QVD usage across apps
# ---------------------------------------------------------------------------

class GetQvdFieldUsageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    qvd_qri: str = Field(
        ...,
        description="QRI of the base QVD (the secureQri field returned by qlik_search_qvd)",
        min_length=1,
    )
    dataset_id: str = Field(
        ...,
        description=(
            "resourceId of the QVD in the catalog (the resourceId field from qlik_search_qvd). "
            "Used to fetch the full field list from the data-sets API."
        ),
        min_length=1,
    )
    app_qris: list[str] = Field(
        ...,
        description=(
            "List of dependent app QRIs (e.g. ['qri:app:sense://GUID1', ...]). "
            "Obtained from qlik_get_qvd_impact."
        ),
        min_length=1,
    )


@mcp.tool(
    name="qlik_get_qvd_field_usage",
    annotations={
        "title": "Analyze QVD Field Usage Across Apps",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def qlik_get_qvd_field_usage(params: GetQvdFieldUsageInput) -> str:
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
                        "note": str | null
                    }
                }
            }
        Or "Error: <message>" on failure.
    """
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
            if fields is None:
                per_app[app_qri] = {
                    "fields": [],
                    "field_count": 0,
                    "note": "qvd_not_referenced",
                }
            else:
                per_app[app_qri] = {
                    "fields": fields,
                    "field_count": len(fields),
                    "note": None,
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


if __name__ == "__main__":
    mcp.run()
