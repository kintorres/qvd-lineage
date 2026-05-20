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


if __name__ == "__main__":
    mcp.run()
