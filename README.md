# QVD Lineage

A Claude Code MCP server that helps Qlik developers discover which fields of a QVD file are used — or never used — by Qlik apps. Type `/analyze-qvd <name>` in Claude and get a full field-usage breakdown, including an interactive visual dashboard, in seconds.

---

## Prerequisites

- Python 3.10 or later
- [Claude Code](https://claude.ai/code) installed
- A Qlik Cloud API key ([how to create one](https://help.qlik.com/en-US/cloud-services/Subsystems/Hub/Content/Sense_Hub/Admin/mc-api-keys.htm))

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/kintorres/qvd-lineage.git
cd qvd-lineage
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Claude Code

Open your Claude MCP configuration file and add the server entry below.

**Configuration file location:**

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**macOS** — add this inside the `"mcpServers"` object (replace the path and credentials):

```json
"qlik": {
  "command": "python3",
  "args": ["/Users/YOUR_USERNAME/qvd-lineage/qlik_mcp.py"],
  "env": {
    "QLIK_BASE_URL": "https://your-tenant.us.qlikcloud.com",
    "QLIK_API_KEY": "your-api-key-here"
  }
}
```

**Windows** — add this inside the `"mcpServers"` object (replace the path and credentials):

```json
"qlik": {
  "command": "python",
  "args": ["C:\\Users\\YOUR_USERNAME\\qvd-lineage\\qlik_mcp.py"],
  "env": {
    "QLIK_BASE_URL": "https://your-tenant.us.qlikcloud.com",
    "QLIK_API_KEY": "your-api-key-here"
  }
}
```

Restart Claude Code after saving the file.

### 4. Install the analysis skill

**macOS:**

```bash
mkdir -p ~/.claude/plugins/qvd-lineage/skills
cp .claude/skills/analyze-qvd.md ~/.claude/plugins/qvd-lineage/skills/
```

**Windows (PowerShell):**

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\plugins\qvd-lineage\skills"
Copy-Item ".claude\skills\analyze-qvd.md" "$env:USERPROFILE\.claude\plugins\qvd-lineage\skills\"
```

Restart Claude Code after copying the file.

---

## Usage

### Option A — Claude Code (terminal)

Open Claude Code in the cloned folder:

```bash
claude .
```

Then type the slash command with the QVD name:

```
/analyze-qvd SalesData
```

### Option B — Claude Desktop (visual app)

If you prefer the graphical interface, open the **Claude Desktop** app. The Qlik tools are automatically available once the MCP server is configured (Step 3 above). Just describe what you want in plain language:

> "Analyze the QVD named SalesData — show me which fields are used by each app and which are never used."

Claude will automatically:
1. Search for the QVD in your Qlik Cloud tenant
2. If multiple QVDs share the same name, present a **clickable visual picker** so you can choose the right one
3. Find all apps that depend on it and resolve their human-readable names
4. Fetch and parse each app's load script to determine field usage
5. Present a text summary of used and unused fields
6. Render an **interactive dashboard widget** directly in the chat (hero metrics, usage matrix, unused field badges)

---

## Available Tools

These tools are called automatically by `/analyze-qvd`, but you can also invoke them directly in Claude.

| Tool | What it does |
|------|-------------|
| `qlik_search_qvd` | Search for a QVD by name; returns `resourceId` and `secureQri` needed for subsequent calls |
| `qlik_get_qvd_impact` | Find all Qlik apps that depend on a given QVD and return their human-readable names in a single call |
| `qlik_get_qvd_field_usage` | Identify which QVD fields each app uses, and which are never used by any app |

---

## How Field Usage Is Detected

`qlik_get_qvd_field_usage` fetches and parses each app's **load script** to determine field usage. This is more accurate than inspecting the data model alone, which misses fields that are renamed, used inside expressions, or filtered out before reaching the model.

### What the parser handles

| Pattern | Example | Detected? |
|---------|---------|-----------|
| Plain field reference | `CustomerID` | ✅ |
| Bracket-quoted name | `[Customer ID]` | ✅ |
| Double-quoted name | `"Customer ID"` | ✅ |
| Renamed field | `CustomerID AS CustID` | ✅ (finds `CustomerID`) |
| Function call | `Year(OrderDate)` | ✅ (finds `OrderDate`) |
| String concatenation | `TRIM(A & 'x' & B)` | ✅ (finds `A` and `B`) |
| Multi-branch expression | `If(Hotel='X', f1, f2)` | ✅ (finds `Hotel`, `f1`, `f2`) |
| Arithmetic | `Price * Qty` | ✅ (finds `Price`, `Qty`) |
| `WHERE` clause | `WHERE Status = 'Active'` | ✅ (finds `Status`) |
| `GROUP BY` / `ORDER BY` | `GROUP BY Hotel, ANO` | ✅ |
| `LOAD *` wildcard | `LOAD * FROM ...` | ✅ (returns all fields) |
| `$(variable)` in path | `FROM $(vPath)Sales.qvd` | ✅ (variable expanded) |
| `/* block */` comments | commented-out expressions | ✅ (stripped before parsing) |
| `// line` comments | `// old field AS x` | ✅ (stripped before parsing) |
| `'string literals'` | `'E'` in concatenation | ✅ (not mistaken for field `E`) |

### Per-app result notes

Each app in the result includes a `note` field:

| Note | Meaning |
|------|---------|
| `null` | Script was parsed successfully; `fields` list is accurate |
| `"script_unavailable"` | The app's script could not be fetched (permissions, app not found, etc.) |
| `"qvd_not_referenced"` | The app's script was fetched but contains no `LOAD … FROM … .qvd` block referencing this QVD |

---

## Running Tests

```bash
python3 -m pytest tests/test_qlik_mcp.py -v
```

The test suite covers all pure parsing helpers end-to-end (49 tests):
- `_extract_qvd_name_from_qri`
- `_resolve_variables`
- `_strip_script_comments`
- `_extract_identifiers_from_expression`
- `_parse_qvd_fields_from_script`
- `_split_field_list` / `_extract_field_from_expression`
- `_fetch_app_script` (async, mocked)
- `qlik_get_qvd_field_usage` integration (mocked)

---

## Troubleshooting

**"QLIK_BASE_URL and QLIK_API_KEY environment variables must be set"**
The credentials are missing from the MCP config. Open your `claude_desktop_config.json` and verify both values are present under the `"env"` key for the `"qlik"` server entry.

**Error 401 — Unauthorized**
Your API key is invalid or has been revoked. Generate a new one in the Qlik Cloud Management Console under **Settings → API Keys**.

**Error 404 — Not Found**
The resource could not be found in your tenant. Verify the `QLIK_BASE_URL` points to the correct tenant (e.g., `https://your-tenant.us.qlikcloud.com`).

**A field I can see in the load script is missing from the results**
The parser scans for field names that match the QVD schema. If the field appears only inside a `/* block comment */` or `// line comment`, it is correctly ignored. If it genuinely appears in an active expression and is still missing, please open an issue with the relevant script snippet.
