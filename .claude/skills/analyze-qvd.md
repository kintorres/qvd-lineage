# Analyze QVD Field Usage

Run the full QVD field-usage analysis pipeline from start to finish, then present a clean structured summary. Do not pause for intermediate confirmation between steps — run all tool calls automatically.

## Step 1 — Identify the QVD

If the user provided a QVD name as an argument, use it directly. Otherwise ask: "What is the name of the QVD you want to analyze?"

Call `qlik_search_qvd` with the provided name.

- **No results:** Tell the user no QVD was found matching that name, and stop.
- **Exactly one result:** Proceed automatically.
- **Multiple results:** Show a numbered list with each item's name and space. Ask the user to pick one before continuing.

From the selected result, extract:
- `resourceId` → used in Step 4 as `dataset_id`
- `secureQri` → used in Steps 2 and 4 as `qvd_qri`

## Step 2 — Find dependent apps

Call `qlik_get_qvd_impact` with the `secureQri` from Step 1.

Collect all entries from the `nodes` array where the QRI starts with `qri:app:sense://`. These are the apps that consume this QVD.

If no app nodes are found, report: "No apps currently depend on this QVD." and stop.

## Step 3 — Resolve app names

For each app QRI collected in Step 2, call `qlik_get_app_name`.

Build a mapping of `{ app_qri: app_name }` to use in the final summary. If a name cannot be resolved, fall back to the raw QRI.

## Step 4 — Analyze field usage

Call `qlik_get_qvd_field_usage` with:
- `qvd_qri`: the `secureQri` from Step 1
- `dataset_id`: the `resourceId` from Step 1
- `app_qris`: the full list of app QRIs from Step 2

## Step 5 — Present summary

Present the results in this exact format. Replace all app QRIs with the human-readable names resolved in Step 3.

---

## QVD Analysis: <qvd_name>

**Total fields:** <total_qvd_fields> | **Apps analyzed:** <apps_analyzed>

### Fields Used

| Field | Used In |
|-------|---------|
| <field_name> | <App Name A>, <App Name B> |

### Fields Never Used

- <field_name>
- <field_name>

_(If all fields are used by at least one app, write: "All fields are used by at least one app.")_

---
