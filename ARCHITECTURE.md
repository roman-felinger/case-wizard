# case-wizard Architecture

Complete system design: agents, skills, progress reporting, and data flow.

## High-Level Pipeline

```
User opens app
    ↓
Health checks run
    ├─ Python 3.8+ ✅
    ├─ Git ✅
    ├─ Claude CLI ✅
    ├─ Claude Logged In ✅
    ├─ CRM Tab ⚠️
    └─ Azure DevOps Config ❌
    ↓
Setup wizard runs
    ├─ [🔗 Open CRM]
    ├─ ✅ Logged in?
    ├─ Organization URL: [_________]
    ├─ PAT Token: [_________]
    └─ [✅ Complete Setup]
    ↓
Configuration saved
    ├─ PAT → Windows Credential Manager (encrypted)
    ├─ URL → .streamlit_config.json
    └─ App restarts
    ↓
Main interface appears
    ├─ Brief tab (Run Brief)
    ├─ Guide tab (Run Guide)
    ├─ Solve tab (Run Solve)
    ├─ Status tab (View progress)
    └─ Settings tab (Edit config)
```

## Stage Execution Flow

### BRIEF: case-brief/case_brief.py

```
input: case_number (e.g., T2611845)

progress📍 "Extracting case context from CRM..."
    ├─ Launch Chromium automation
    ├─ Poll for authenticated CRM tab
    └─ Scrape case details
progress✅ "CRM data extracted"

progress📍 "Querying Azure DevOps..."
    ├─ Find branches with case number in name
    ├─ Find PRs with case number in title/description
    └─ Get commit history
progress✅ "Azure DevOps search complete"

progress📍 "Building markdown brief..."
    ├─ Merge CRM + ADO data
    ├─ Format as markdown
    └─ Suggest repos for git clone
progress✅ "Brief complete"

output: case-briefs/case-T2611845.md
```

**No Claude AI involved.** Pure data scraping.

---

### GUIDE: case-guide/case_guide.py

```
input: case_number (from Brief step)

progress📍 "Reading case brief..."
    └─ Load case-briefs/case-T2611845.md
progress✅ "Brief loaded"

progress📍 "Calling Claude for guide generation..."
    ├─ Prepare prompt with case brief
    ├─ Use agent: case-guide
    ├─ Send to Claude via CLI or API
    └─ Wait for response
progress✅ "Guide generation complete"

progress📍 "Writing guide document..."
    ├─ Format Claude's response as markdown
    └─ Save to case-guides/
progress✅ "Guide ready"

output: case-guides/case-T2611845-for-dummies.md
```

**1 Claude AI call:**
- **Agent:** case-guide
- **Input:** Case brief
- **Output:** Step-by-step implementation guide
- **Time:** ~5-10 seconds
- **Tokens:** ~2,000-5,000

---

### SOLVE: case-solve/case_solve.py

```
input: case_number (from Guide step)

progress📍 "Reading guide..."
    └─ Load case-guides/case-T2611845-for-dummies.md
progress✅ "Guide loaded"

progress📍 "Cloning repository..."
    ├─ Get repo URL from guide or prompt
    ├─ Clone to case-solves/repos/<name>/
    └─ Create branch: case/T2611845
progress✅ "Repository ready"

progress📍 "Installing dependencies..."
    ├─ Detect: pip/npm/cargo/dotnet
    ├─ Run: pip install / npm install / etc
    └─ Cache for future runs
progress✅ "Dependencies installed"

---
PHASE 1: PLANNING
---

progress📍 "Generating implementation plan..."
    ├─ Prepare prompt with guide + repo
    ├─ Use agent: case-solver
    ├─ Send to Claude via CLI or API
    └─ Wait for response
progress✅ "Plan generated"

progress📍 "Showing plan to user..."
    ├─ Display: --show-plan output
    └─ Wait for: user confirmation
progress✅ "Plan approved by user"

---
PHASE 2: IMPLEMENTATION
---

progress📍 "Applying changes..."
    ├─ For each file in plan:
    │   ├─ Read current file
    │   ├─ Apply planned changes
    │   ├─ Write updated file
    │   └─ Commit
    └─ Process in dependency order
progress✅ "All changes applied"

progress📍 "Running tests..."
    ├─ npm test / pytest / cargo test
    └─ Report results
progress✅ "Tests pass"

progress📍 "Running linter..."
    ├─ eslint / black / clippy
    └─ Auto-fix if possible
progress✅ "Lint passes"

progress📍 "Building..."
    ├─ npm run build / cargo build
    └─ Check for errors
progress✅ "Build succeeds"

progress📍 "Generating verification checklist..."
    ├─ List all commits
    ├─ List all files changed
    ├─ Create manual test steps
    └─ Save to VERIFICATION_CHECKLIST.md
progress✅ "Verification ready"

output:
  ├─ case-solves/case-T2611845/
  │   ├─ repo/                          (cloned + modified)
  │   └─ VERIFICATION_CHECKLIST.md     (next steps)
  └─ Git branch: case/T2611845          (on repo with all commits)
```

**2 Claude AI calls:**
1. **Planning phase:**
   - **Agent:** case-solver
   - **Input:** Guide + repo structure
   - **Output:** Implementation plan
   - **Time:** ~10-30 seconds
   - **Tokens:** ~5,000-10,000

2. **Implementation phase:**
   - **Agent:** case-solver
   - **Input:** Plan + current files
   - **Output:** Modified files + commits
   - **Time:** ~30-120 seconds
   - **Tokens:** ~10,000-50,000

---

## Component Architecture

### Core Modules

```
case-wizard/
├─ app/
│   ├─ main.py           # Streamlit UI, orchestrates stages
│   ├─ settings.py       # Config management, keyring
│   ├─ checks.py         # Health checks, system verification
│   └─ progress.py       # Progress reporting for UI
│
├─ lib/
│   ├─ progress.py       # JSON progress messages for subprocesses
│   ├─ crm_scrape.py     # Dynamics 365 browser automation
│   ├─ ado_api.py        # Azure DevOps REST API queries
│   ├─ bc_scrape.py      # Business Central (optional)
│   └─ report.py         # Markdown report generation
│
├─ case-brief/
│   ├─ case_brief.py     # Extract context (ALGORITHMIC)
│   └─ lib/              # Shared scraping libraries
│
├─ case-guide/
│   ├─ case_guide.py     # Create guides (CALLS CLAUDE x1)
│   └─ lib/              # Helpers
│
├─ case-solve/
│   ├─ case_solve.py     # Auto-implement (CALLS CLAUDE x2)
│   ├─ lib/
│   │   ├─ workspace.py  # Clone, branch, dependencies
│   │   ├─ implementer.py # Apply changes from guide
│   │   ├─ verifier.py   # Run tests, lint, build
│   │   ├─ committer.py  # Git commits with messages
│   │   └─ report.py     # Verification checklist
│   └─ case-solves/      # Output: cloned repos + branches
│
├─ .claude/
│   ├─ agents/
│   │   ├─ case-brief.md     # Reference only (no AI)
│   │   ├─ case-guide.md     # Claude agent persona
│   │   └─ case-solver.md    # Claude agent persona
│   └─ skills/
│       ├─ extract-context.md    # Context consolidation
│       └─ generate-plan.md      # Plan generation
│
├─ SETUP.md          # Health check & config flow
├─ AI-CALLS.md       # This document
├─ ARCHITECTURE.md   # This file
└─ README.md         # Main docs
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ User: case number, case-wizard UI                          │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────▼──────────────────────┐
        │ case-brief/case_brief.py          │
        │ (ALGORITHMIC)                     │
        │                                   │
        │ • Browser scrape CRM              │
        │ • Query ADO API                   │
        │ • Merge into markdown             │
        └────────────────────┬──────────────┘
                             │
                    case-briefs/
                    case-T2611845.md
                             │
        ┌────────────────────▼──────────────────────┐
        │ case-guide/case_guide.py                  │
        │ (CLAUDE AI x1)                            │
        │                                           │
        │ • Read brief                              │
        │ • Call Claude → create guide              │
        │ • Write markdown                          │
        └────────────────────┬──────────────────────┘
                             │
                    case-guides/
                case-T2611845-for-dummies.md
                             │
        ┌────────────────────▼──────────────────────┐
        │ case-solve/case_solve.py                  │
        │ (CLAUDE AI x2)                            │
        │                                           │
        │ • Clone repo                              │
        │ • Call Claude #1 → generate plan          │
        │ • Call Claude #2 → apply changes          │
        │ • Run tests/lint/build                    │
        │ • Create commits                          │
        │ • Generate checklist                      │
        └────────────────────┬──────────────────────┘
                             │
                    case-solves/case-T2611845/
                    ├─ repo/              (with branch)
                    └─ VERIFICATION_CHECKLIST.md
                             │
                             ▼
                      ✅ READY FOR PR
```

---

## Progress Reporting Architecture

### Flow

```
Subprocess (case-brief/guide/solve)
    ↓
    Emits JSON: {"operation": "...", "status": "...", "detail": "..."}
    ↓
Main app (streamlit)
    ↓
    Streams lines from subprocess
    ↓
    Parses JSON
    ↓
    ProgressReporter tracks messages
    ↓
    UI updates in real-time
    ├─ Current operation
    ├─ Status emoji (📍/✅/❌/⚠️)
    ├─ Detail message
    ├─ Progress % (if available)
    └─ Last 10 messages visible
```

### Progress Messages

Format: **JSON, one per line**

```json
{
  "operation": "Extracting case context from CRM...",
  "status": "running",
  "detail": "Scraping case T2611845",
  "progress_pct": 25
}
```

Status values:
- `running` → 📍 Currently executing
- `success` → ✅ Completed successfully
- `error` → ❌ Failed
- `warning` → ⚠️ Non-critical issue

---

## Configuration Storage

### Secrets (Windows Credential Manager)

```
Service: case-wizard
Credential: azdo_pat
Value: [encrypted by OS]
Used for: Azure DevOps API authentication
```

Access from Python:
```python
import keyring
pat = keyring.get_password("case-wizard", "azdo_pat")
keyring.set_password("case-wizard", "azdo_pat", "new_value")
keyring.delete_password("case-wizard", "azdo_pat")
```

### Settings (Local JSON File)

```
app/.streamlit_config.json
{
  "azdo_org_url": "https://dev.azure.com/myorg",
  "open_in_vscode": true,
  "run_tests": false,
  "run_lint": false,
  "run_build": false,
  "...": "..."
}
```

---

## Agent Invocation Methods

### Method 1: CLI Prompt (Current)

```bash
claude -p << 'EOF'
You are case-guide agent.
Create an implementation guide from this brief:

<brief content>
EOF
```

### Method 2: Agent Registry (Future)

When Claude Code agents are fully implemented:

```bash
claude -a case-guide << 'EOF'
<brief content>
EOF
```

### Method 3: Managed Agents (Future)

Anthropic Managed Agents API:

```python
import anthropic
client = anthropic.Anthropic()
response = client.agents.messages.create(
    agent_id="case-guide",
    thread_id="...",
    input="<brief content>"
)
```

---

## Cost & Performance

### Per-Case Costs

| Stage | Type | Calls | Est. Cost |
|-------|------|-------|-----------|
| brief | Algorithmic | 0 | $0 |
| guide | Claude AI | 1 | $0.002-0.008 |
| solve | Claude AI | 2 | $0.002-0.015 |
| **TOTAL** | — | **3** | **$0.004-0.023** |

(Assuming Claude 3.5 Sonnet pricing)

### Per-Case Timing

| Stage | Time |
|-------|------|
| brief | 2-5 min (browser + API) |
| guide | 1-2 min (Claude + formatting) |
| solve | 2-5 min (planning + implementation) |
| **TOTAL** | **5-12 min** |

---

## Error Handling

### Graceful Degradation

If a stage fails:

1. **case-brief CRM fails** → Use ADO-only data
2. **case-brief ADO fails** → Use CRM-only data
3. **case-guide fails** → Show error, retry option
4. **case-solve plan fails** → Show error, retry option
5. **case-solve apply fails** → Revert changes, cleanup

### User Feedback

Progress reporting shows:
- ✅ What succeeded
- ❌ What failed (with error message)
- ⚠️ What might need attention
- 📍 What's currently running

---

## Security Considerations

### Secrets

- ✅ PAT tokens in Credential Manager (OS-encrypted)
- ✅ Claude CLI auth handled by `claude login`
- ❌ Never store secrets in config files
- ❌ Never log full tokens/secrets

### Permissions

- ✅ Repos cloned with user's git creds (SSH or https)
- ✅ Azure DevOps API uses user's PAT (scoped to Code Read)
- ✅ CRM scraping uses user's browser session (already logged in)

### Data

- ✅ Brief/guides stored locally
- ✅ Cloned repos in local case-solves/ directory
- ✅ No data uploaded to external services
- ✅ Claude API calls are standard (handled by Anthropic)

---

## Extensibility

### Adding a New Stage

1. Create `case-xxx/case_xxx.py`
2. Create `.claude/agents/case-xxx.md` (if uses Claude)
3. Emit progress via `lib.progress`
4. Add tab to `app/main.py` calling the stage

### Customizing Agents

1. Edit `.claude/agents/*.md` for persona/instructions
2. Update prompts in stage scripts
3. Can switch between Claude models as needed

### Adding Skills

1. Create `.claude/skills/new-skill.md`
2. Reference in agent descriptions
3. Implement in actual stage code

---

## Conclusion

**case-wizard is a 3-stage pipeline:**

1. **Brief** (Algorithmic): Scrape data → compile markdown
2. **Guide** (AI-assisted): Claude reads brief → creates guide
3. **Solve** (AI-assisted): Claude reads guide → implements changes

**3 total Claude AI calls per case**
**~$0.005-0.023 per case**
**~5-12 minutes per case**
**Full progress visibility**

Everything is observable, configurable, and extends naturally. ✨
