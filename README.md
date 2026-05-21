# QVD Lineage

A Claude Code MCP server that helps Qlik developers discover which fields of a QVD file are used — or never used — by Qlik apps. Type `/analyze-qvd <name>` in Claude and get a full field-usage breakdown in seconds.

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
  "args": ["/Users/kintorres/qvd-lineage/qlik_mcp.py"],
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
  "args": ["C:\\Users\\kintorres\\qvd-lineage\\qlik_mcp.py"],
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

Open Claude Code in the cloned folder:

```bash
claude .
```

Then type the slash command with the QVD name:

```
/analyze-qvd SalesData
```

Claude will automatically:
1. Search for the QVD in your Qlik Cloud tenant
2. Find all apps that depend on it
3. Analyze which fields each app uses
4. Present a table of used fields and a list of fields never used by any app

---

## Available Tools

These tools are called automatically by `/analyze-qvd`, but you can also invoke them directly in Claude.

| Tool | What it does |
|------|-------------|
| `qlik_search_qvd` | Search for a QVD by name; returns `resourceId` and `secureQri` needed for subsequent calls |
| `qlik_get_qvd_impact` | Find all Qlik apps that depend on a given QVD |
| `qlik_get_app_name` | Resolve an app QRI to a human-readable name |
| `qlik_get_qvd_field_usage` | Identify which QVD fields each app uses, and which are never used by any app |

---

## Troubleshooting

**"QLIK_BASE_URL and QLIK_API_KEY environment variables must be set"**
The credentials are missing from the MCP config. Open your `claude_desktop_config.json` and verify both values are present under the `"env"` key for the `"qlik"` server entry.

**Error 401 — Unauthorized**
Your API key is invalid or has been revoked. Generate a new one in the Qlik Cloud Management Console under **Settings → API Keys**.

**Error 404 — Not Found**
The resource could not be found in your tenant. Verify the `QLIK_BASE_URL` points to the correct tenant (e.g., `https://your-tenant.us.qlikcloud.com`).
