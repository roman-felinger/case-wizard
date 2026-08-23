# case-brief: Scrape & Compile Case Context

**NOT a Claude agent.** This is a pure data-scraping pipeline.

Your job is to extract and compile case context from three sources:
1. **Dynamics 365 CRM** — Browser automation scraping
2. **Azure DevOps REST API** — Query via PAT token
3. **Business Central** — Optional browser scraping

**No AI involved.** Just extract, validate, and compile into markdown.

## What You Output

A markdown file (`case-brief.md`) containing:

```markdown
# Case T2611845: Brief Title

## 📋 Summary
1-sentence overview of what needs to be solved

## 👤 Customer
- Name: Company Inc
- Contact: email@company.com
- Industry: Tech/Retail/etc

## 🔴 Problem
What's broken, why it matters, what the customer reported

## 🔧 Scope
What's in scope (quick list):
- Fix bug in X module
- Update Y configuration
- Add Z feature

## 📊 Context
- Affected modules: backend, frontend, database
- Tech stack: Node.js, React, PostgreSQL
- Deployment: Azure App Service

## 🔗 Related Items
- Azure DevOps: https://dev.azure.com/...
- PR #123 (related change)
- Commit abc123... (context)

## ⏱️ Constraints
- Deadline: Aug 25
- Criticality: P1 / P2 / P3
- Can't modify X (breaking change)
```

## How It Works (Algorithmic)

1. **Browser Scraping (CRM)**
   - Launch Chromium automation profile
   - Poll for authenticated CRM tab
   - Extract HTML fields: case number, title, description, customer, status
   - Parse as structured data

2. **REST API Query (Azure DevOps)**
   - Use PAT token (from environment)
   - Search branches/PRs where name/title contains case number
   - Get commit history for context
   - Handle pagination and truncation

3. **Markdown Compilation**
   - Merge CRM + ADO data
   - Format as readable brief
   - Link to original URLs
   - Include suggested repos for git clone

## Key Behaviors

- ✅ **Assume CRM tab is open** — Don't prompt for login
- ✅ **Use Azure DevOps API** — PAT is in environment
- ✅ **Extract, don't interpret** — Report facts, not opinions
- ✅ **Be concise** — Brief should be readable in 2 min
- ✅ **Link everything** — Include URLs to CRM, PRs, commits

## Progress Reporting

Report progress as you work:
```
📍 Extracting case context from CRM...
✅ Found case T2611845: "Fix login timeout"
📍 Querying Azure DevOps for related items...
✅ Found 3 related PRs
📍 Building summary brief...
✅ Brief ready: 1.2 KB
```

## Environment

You have access to:
- `AZDO_ORG_URL` — Azure DevOps organization
- `AZDO_PAT` — Personal access token (scopes: Code Read, Project Read)
- Browser automation for CRM scraping

## Failure Modes

If CRM scraping fails:
- Check: Dynamics 365 tab is open + logged in
- Retry: Browser tab refresh

If Azure DevOps fails:
- Check: PAT is valid and has required scopes
- Check: Organization URL is correct
- Retry: API calls

If both fail:
- Return partial brief with what you have
- Report: "CRM unavailable" or "ADO unavailable"
- User can retry

## Success Criteria

Brief is ready when:
- ✅ Case number and title extracted
- ✅ Customer info present
- ✅ Problem statement clear
- ✅ Scope defined
- ✅ Related ADO items linked
- ✅ All URLs working
