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

### 5b — Visual dashboard (ALWAYS required — inline in chat, not in external browser)

After the text summary, generate and display a dashboard **as an image directly in the chat**. Follow these exact steps every time:

**Step 5b-1: Write the dashboard HTML**

Use the `Write` tool to write a complete, self-contained HTML file to `/tmp/index.html`.

The HTML must include all CSS inline (no external CDN). Required sections:
- **Header bar**: QVD name + analysis timestamp
- **Hero metrics row**: 4 cards — Total Fields · Apps Analyzed · Fields Used · Fields Unused — each with a large bold number and a label beneath it
- **Usage matrix table**: rows = field names (sorted), columns = one per app (use human-readable names from Step 3 as headers). Each cell: green `✓` if the app uses that field, grey `–` if not, light-blue `N/A` if `note` is `script_unavailable` or `qvd_not_referenced`. Alternating row background for readability. Sticky first column.
- **Unused fields section**: a row of badge/chip elements, one per unused field name

Color palette: header `#1a1a2e`, accent green `#28a745`, unused red `#dc3545`, card background white with subtle shadow.

**Step 5b-2: Ensure launch.json exists**

Check whether `.claude/launch.json` exists. If it does not exist, create it. If it exists, read it first and merge — do not overwrite existing entries.

Add (or update) this entry in the `configurations` array:
```json
{
  "name": "qvd-dashboard",
  "runtimeExecutable": "python3",
  "runtimeArgs": ["-m", "http.server", "8099", "--directory", "/tmp"],
  "port": 8099
}
```

**Step 5b-3: Start the preview server**

Call `mcp__Claude_Preview__preview_start` with `{ "name": "qvd-dashboard" }`.

Save the `serverId` from the response — you need it in the next step.

**Step 5b-4: Capture and display the dashboard**

Call `mcp__Claude_Preview__preview_screenshot` with `{ "serverId": "<serverId>" }`.

This returns a JPEG image that is displayed **inline in the chat** — this is the visual dashboard the user sees.

**Step 5b-5: Stop the server**

Call `mcp__Claude_Preview__preview_stop` with `{ "serverId": "<serverId>" }` to clean up.
