# Analyze QVD Field Usage

Run the full QVD field-usage analysis pipeline from start to finish, then present a clean text summary **and** a visual HTML dashboard. Do not pause for intermediate confirmation between pipeline steps — run all tool calls automatically.

---

## Step 1 — Identify the QVD

If the user provided a QVD name as an argument, use it. Otherwise ask: "What is the name of the QVD you want to analyze?"

Call `qlik_search_qvd` with the provided name.

- **No results:** Tell the user no QVD was found matching that name, and stop.

- **Exactly one result:** Proceed automatically.

- **Multiple results:** You MUST use the `AskUserQuestion` tool — do NOT present a text list. Build one question with one option per result:
  ```
  AskUserQuestion({
    questions: [{
      question: "Found multiple QVDs with that name. Which one do you want to analyze?",
      header: "Select QVD",
      multiSelect: false,
      options: [
        {
          label: "<name> — <resourceSubType>",
          description: "Space ID: <spaceId> · Updated: <updatedAt>"
        },
        ...one entry per search result...
      ]
    }]
  })
  ```
  Wait for the user's selection before continuing. Map the selected label back to the correct search result to obtain `resourceId` and `secureQri`.

From the selected result, extract:
- `resourceId` → used in Step 4 as `dataset_id`
- `secureQri` → used in Steps 2 and 4 as `qvd_qri`

---

## Step 2 — Find dependent apps

Call `qlik_get_qvd_impact` with the `secureQri` from Step 1.

Collect all entries from the `nodes` object where the key starts with `qri:app:sense://`. These are the apps that consume this QVD.

If no app nodes are found, report: "No apps currently depend on this QVD." and stop.

---

## Step 3 — Resolve app names

For each app QRI collected in Step 2, call `qlik_get_app_name`.

Build a mapping of `{ app_qri → app_name }` to use in Steps 4 and 5. If a name cannot be resolved, fall back to the raw QRI.

---

## Step 4 — Analyze field usage

Call `qlik_get_qvd_field_usage` with:
- `qvd_qri`: the `secureQri` from Step 1
- `dataset_id`: the `resourceId` from Step 1
- `app_qris`: the full list of app QRIs from Step 2

---

## Step 5 — Present results

### 5a — Text summary

Present the results in this exact format. Replace all app QRIs with the human-readable names from Step 3.

---

### QVD Analysis: \<qvd_name\>

**Total fields:** \<total_qvd_fields\> | **Apps analyzed:** \<apps_analyzed\>

#### Fields Used

| Field | Used In |
|-------|---------|
| \<field_name\> | \<App Name A\>, \<App Name B\> |

#### Fields Never Used

- \<field_name\>

_(If all fields are used by at least one app, write: "All fields are used by at least one app.")_

---

### 5b — Visual dashboard (ALWAYS required — do this for every model)

After the text summary, you MUST generate and open an HTML dashboard. Follow these exact steps:

**Step 5b-1: Build the HTML string**

Create a complete, self-contained HTML file. It must contain all styles inline (no external CDN dependencies). Structure:

```
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>QVD Analysis — {qvd_name}</title>
  <style>
    /* Use a clean sans-serif font, white background, subtle shadows */
    /* Hero metrics row: 4 cards — Total Fields, Apps Analyzed, Fields Used, Fields Unused */
    /* Each metric card: large bold number + label below */
    /* Usage matrix table: sticky first column (field names), one column per app */
    /*   Used cell:   green background (#d4edda), checkmark ✓ */
    /*   Unused cell: light grey (#f8f9fa), dash – */
    /* Unused fields section: badge-style chips for each field name */
    /* Color palette: header #1a1a2e, accent #4CAF50, unused #dc3545 */
  </style>
</head>
<body>
  <!-- Header bar with QVD name and timestamp -->
  <!-- Hero metrics: 4 cards -->
  <!-- Usage matrix: scrollable table, rows=fields, columns=apps -->
  <!-- Unused fields: grid of chips -->
</body>
</html>
```

Populate every section with the actual data from Step 4. Use the human-readable app names from Step 3 as column headers. Fields with `note: "script_unavailable"` or `note: "qvd_not_referenced"` should show a grey `N/A` cell.

**Step 5b-2: Write the file**

Use the `Write` tool to write the complete HTML to `/tmp/qvd-dashboard.html`.

**Step 5b-3: Open in browser**

Use `ToolSearch` to load `mcp__Claude_in_Chrome__tabs_context_mcp` and `mcp__Claude_in_Chrome__navigate`, then:

1. Call `mcp__Claude_in_Chrome__tabs_context_mcp` — get the list of available tabs and pick any tab ID from the current group.
2. Call `mcp__Claude_in_Chrome__navigate` with `{ tabId: <id>, url: "file:///tmp/qvd-dashboard.html" }`.

If no Chrome tabs are available, fall back to running: `open /tmp/qvd-dashboard.html` via the `Bash` tool.
