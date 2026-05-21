# Script-Based QVD Field Usage — Design

**Date:** 2026-05-21
**Status:** Approved

---

## Problem

The current `qlik_get_qvd_field_usage` tool intersects QVD schema fields with the app's in-memory data model (`GET /api/v1/apps/{appId}/data/metadata`). This approach fails in three common cases:

1. **Renamed fields** — `CustomerID AS CustID` loads `CustomerID` from the QVD but the data model only shows `CustID`, so the intersection misses it.
2. **Fields used in expressions** — `Year(OrderDate) AS OrderYear` uses `OrderDate` from the QVD but it never appears directly in the data model.
3. **Dropped fields** — a field loaded from the QVD and then dropped via `DROP FIELD` disappears from the data model but was still loaded.

## Solution

Replace the data model intersection with **load script parsing**: fetch each app's load script via the Qlik Cloud API and parse it to find which QVD fields are actually referenced in LOAD statements.

---

## Scope

- **Modified:** `qlik_mcp.py` — internals of `qlik_get_qvd_field_usage` + two new private helpers
- **Unchanged:** tool name, parameters, return format, skill, README, all other tools

---

## New Private Helpers

### `_fetch_app_script(app_id: str) -> str | None`

Fetches the latest load script text for an app.

1. Call `GET /api/v1/apps/{app_id}/scripts` → get list of script versions
2. Pick the most recent version by `createdAt` (or first in list)
3. Call `GET /api/v1/apps/{app_id}/scripts/{id}` → get script content
4. Return the script text string, or `None` on any failure

### `_parse_qvd_fields_from_script(script: str, qvd_name: str, all_qvd_fields: list[str]) -> list[str]`

Pure function — no API calls. Returns the list of QVD fields referenced in the script.

**Step 1 — Variable resolution**
- Extract all `SET varName = 'value'` and `LET varName = expression` definitions
- Build a `{varName: value}` map
- Do multiple substitution passes replacing `$(varName)` occurrences until no more substitutions are possible (handles nested variables)

**Step 2 — Find matching LOAD blocks**
- Search for FROM clauses where the resolved path contains the QVD name (case-insensitive, ignoring `.qvd` extension and directory prefix)
- Extract the full `LOAD ... FROM ...` block for each match

**Step 3 — Parse the field list**
- `LOAD *` → return all `all_qvd_fields` (wildcard = every field used)
- Otherwise: split field list by comma; for each token:
  - Take the part **before** `AS` (the source expression)
  - Strip wrapping function calls to extract the innermost field name (e.g. `Year(OrderDate)` → `OrderDate`)
  - Keep only names that appear in `all_qvd_fields`

**Step 4 — Return** deduplicated sorted list of matched QVD field names.

---

## Updated `qlik_get_qvd_field_usage` Internal Flow

```
For each app_qri:
  1. Extract app_id from QRI
  2. _fetch_app_script(app_id)
     → None: mark app as script_unavailable, skip
  3. _parse_qvd_fields_from_script(script, qvd_name, all_qvd_fields)
     → empty (no LOAD block found): mark app as qvd_not_referenced
     → list of fields: record per_app fields
```

The QVD name passed to the parser is derived from the `qvd_qri` — extracted as the filename component of the QRI path (e.g. `qri:sense://...Sales...` → `Sales`).

---

## Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Script fetch fails (any HTTP error or timeout) | App marked `"script_unavailable"`, 0 fields, processing continues |
| No LOAD block found referencing this QVD | App marked `"qvd_not_referenced"`, 0 fields |
| Variable partially unresolved (runtime-computed) | Match attempted on partially-resolved string; proceeds if QVD name visible |
| `LOAD *` | All QVD schema fields counted as used for that app |
| QVD schema fetch fails (`dataset_id` endpoint) | Tool returns error immediately — field list is required |

The `per_app` section of the JSON response gains an optional `"note"` field for `script_unavailable` and `qvd_not_referenced` cases.

---

## Return Format (unchanged)

```json
{
  "qvd_qri": "...",
  "total_qvd_fields": 12,
  "apps_analyzed": 3,
  "fields_used": [
    {"field": "CustomerID", "used_in_apps": ["qri:app:sense://..."]}
  ],
  "fields_unused": ["ObsoleteField"],
  "per_app": {
    "qri:app:sense://...": {
      "fields": ["CustomerID", "OrderDate"],
      "field_count": 2,
      "note": null
    },
    "qri:app:sense://...": {
      "fields": [],
      "field_count": 0,
      "note": "script_unavailable"
    }
  }
}
```

---

## Out of Scope

- No changes to tool parameters or return schema keys
- No changes to the skill, README, or any other tool
- No full Qlik script AST parser — regex-based parsing only
- No resolution of runtime-computed variable values
