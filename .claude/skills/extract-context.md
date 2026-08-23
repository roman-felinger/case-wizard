# Skill: Extract Case Context from Multiple Sources

## Overview

Extract and consolidate case context from CRM, Azure DevOps, and related systems.

## When to Use

- Gathering initial case information
- Enriching a brief with related work items
- Finding similar past cases
- Correlating customer info with technical details

## Inputs

```
{
  "case_number": "T2611845",
  "crm_raw": "HTML or text from Dynamics 365 CRM tab",
  "azdo_org_url": "https://dev.azure.com/myorg",
  "azdo_pat": "token_here",
  "include_commits": true,
  "max_prs": 10
}
```

## Outputs

```json
{
  "case_number": "T2611845",
  "case_title": "Fix login timeout issue",
  "customer": {
    "name": "Company Inc",
    "email": "support@company.com",
    "industry": "SaaS"
  },
  "problem": {
    "description": "Users cannot log in when network is slow",
    "severity": "P1",
    "reported_date": "2025-08-20",
    "affected_users": "5000+"
  },
  "scope": [
    "Fix timeout logic in auth service",
    "Update login retry mechanism",
    "Add monitoring"
  ],
  "related_items": {
    "work_items": [
      { "id": "123", "title": "...", "status": "In Progress" }
    ],
    "pull_requests": [
      { "id": "456", "title": "...", "state": "merged" }
    ],
    "commits": [
      { "hash": "abc123", "message": "..." }
    ]
  },
  "constraints": [
    "Cannot change auth database schema",
    "Must maintain backwards compatibility"
  ],
  "deadline": "2025-08-25"
}
```

## Implementation Steps

1. **Parse CRM content**
   - Extract case number, title, description
   - Get customer name, email, company
   - Identify severity, deadline
   - Find related case numbers

2. **Query Azure DevOps**
   - Find work items tagged with case number
   - Get related PRs
   - Extract commit history
   - Correlate by case number in commit messages

3. **Enrich with metadata**
   - Add timestamps
   - Link to original items
   - Identify patterns (similar past cases)
   - Flag blockers/dependencies

4. **Consolidate and validate**
   - Check for missing critical info
   - Validate links
   - Create structured output

## Error Handling

- CRM unavailable: Return what you can from ADO
- ADO unavailable: Return CRM data with note
- Both unavailable: Return error with diagnostics
- Bad case number: Report clearly, suggest search

## Progress Messages

```
📍 Extracting case T2611845 from CRM...
✅ Case title: Fix login timeout
✅ Customer: Company Inc
✅ Severity: P1
📍 Querying Azure DevOps...
✅ Found 3 related work items
✅ Found 2 related PRs
✅ Found 5 related commits
📍 Consolidating...
✅ Context extracted and validated
```
