---
name: analyze-qvd
description: Use when the user asks to analyze a QVD file, check which fields are used by each app, identify unused fields, or run any QVD field-usage or lineage analysis.
---

# Analyze QVD Field Usage

Run the full QVD field-usage analysis pipeline from start to finish, then present a text summary followed by a visual dashboard screenshot **directly in the chat**. Do not pause for intermediate confirmation between pipeline steps — run all tool calls automatically.

---

## Step 1 — Identify the QVD

If the user provided a QVD name as an argument, use it. Otherwise ask: "What is the name of the QVD you want to analyze?"

Call `qlik_search_qvd` with the provided name.

- **No results:** Tell the user no QVD was found matching that name, and stop.

- **Exactly one result:** Proceed automatically.

- **Multiple results:** Use the `AskUserQuestion` tool — do NOT present a text list. Build one question with one option per result:
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
        ... one entry per search result ...
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

### 5b — Visual dashboard (ALWAYS required — inline interactive widget, no files or servers)

After the text summary, emit the dashboard as an **inline artifact** — Claude Desktop renders it as an interactive widget directly in the chat. Do NOT write files, start servers, or take screenshots.

Output the complete self-contained HTML wrapped in an artifact block exactly like this:

```
<antArtifact identifier="qvd-dashboard" type="text/html" title="QVD Analysis — {qvd_name}">
<!DOCTYPE html>
... full HTML here ...
</antArtifact>
```

**Required sections inside the HTML** (all CSS must be inline — no external CDN):

- **Header bar**: QVD name + analysis timestamp
- **Hero metrics row**: 4 cards side by side — Total Fields · Apps Analyzed · Fields Used · Fields Unused — each showing a large bold number with a label beneath
- **Usage matrix table**: rows = field names (sorted A–Z), columns = one per app using human-readable names from Step 3 as headers. Each cell:
  - Green background + `✓` → app uses this field
  - Light grey + `–` → app does not use this field
  - Light blue + `N/A` → `note` is `script_unavailable` or `qvd_not_referenced`
  - Alternating row shading for readability; sticky first column so field names stay visible when scrolling horizontally
- **Unused fields section**: badge/chip elements, one per unused field name

Color palette: header `#1a1a2e`, used green `#28a745`, unused badge red `#dc3545`, card background white with subtle box-shadow.
