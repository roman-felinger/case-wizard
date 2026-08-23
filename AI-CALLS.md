# AI Calls & Agents in case-wizard

Complete breakdown of where Claude AI is called, what agents handle it, and what they do.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│ User enters case number T2611845 and clicks "Run Brief" │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │  Step 1: case-brief │
        │   (ALGORITHMIC)     │
        └──────────┬──────────┘
              NO AI CALLS
      (Browser scrape + API queries)
                   │
        ┌──────────▼──────────────────┐
        │  Step 2: case-guide         │
        │  (CALLS CLAUDE)             │
        │  Agent: claude-code-guide   │
        │  OR Claude prompt via CLI   │
        └──────────┬──────────────────┘
              1 AI CALL
      (Analyze brief → create guide)
                   │
        ┌──────────▼──────────────────┐
        │  Step 3: case-solve         │
        │  (CALLS CLAUDE x2)          │
        │  Agent: claude-solver       │
        │  OR Claude prompt via CLI   │
        └──────────┬──────────────────┘
              2 AI CALLS
      (Plan phase + Apply phase)
                   │
                   ▼
           ✅ COMPLETE
```

---

## Detailed Breakdown

### STEP 1: case-brief (NO AI)

**Script:** `case-brief/case_brief.py`  
**Agent:** None (algorithmic only)  
**AI Calls:** **0**

**What it does:**
1. Scrapes Dynamics 365 CRM (browser automation)
2. Queries Azure DevOps REST API
3. Queries Business Central (optional)
4. Compiles markdown brief

**No Claude involved.** Pure data extraction and compilation.

**Output:** `case-briefs/case-T2611845.md`

---

### STEP 2: case-guide (USES CLAUDE)

**Script:** `case-guide/case_guide.py`  
**Agent:** TBD (claude-code-guide or custom)  
**AI Calls:** **1**

#### Call #1: Generate Implementation Guide

**Input:**
- Case brief (from case-brief output)
- Case number
- (Optional) Codebase context

**Prompt Pattern:**
```
You are case-guide. Given this case brief, create a step-by-step 
implementation guide for developers.

<brief content>

Generate a detailed guide with:
1. Problem explanation
2. Setup instructions
3. Implementation steps (file by file)
4. Testing strategy
5. Deployment plan
```

**Claude's Role:**
- Analyze the problem statement
- Understand scope and constraints
- Reason about solution approach
- Create detailed, actionable steps
- Explain WHY each step (not just WHAT)

**Output:** `case-guides/case-T2611845-for-dummies.md`

---

### STEP 3: case-solve (USES CLAUDE x2)

**Script:** `case-solve/case_solve.py`  
**Agent:** case-solver  
**AI Calls:** **2**

#### Call #1: Generate Implementation Plan

**Input:**
- Implementation guide (from case-guide output)
- Cloned repository structure
- File contents

**Prompt Pattern:**
```
You are case-solver. Given this guide and repo structure, 
create a detailed implementation plan.

<guide content>
<repo structure>

Generate a plan showing:
1. Which files need changes
2. What to change in each file
3. Order of changes (dependency order)
4. Code snippets before/after
5. Test cases for each change
```

**Claude's Role:**
- Understand the guide in depth
- Examine repo structure
- Map guide steps to actual files
- Identify dependencies
- Create testable, ordered steps

**Output:** Shown to user via `--show-plan` (user confirms before proceeding)

#### Call #2: Implement Changes

**Input:**
- Approved implementation plan
- Repository files
- Guide text

**Prompt Pattern:**
```
You are case-solver. Apply this plan to the repository.

For each step:
1. Read the current file
2. Apply the change
3. Verify syntax
4. Generate commit message

<plan content>

Apply changes step by step, creating one logical commit per step.
```

**Claude's Role:**
- Apply each planned change to files
- Generate sensible commit messages
- Handle edge cases (conflicts, etc.)
- Verify syntax/compilation
- Create logical groupings

**Output:**
- Modified files in repo
- Git commits on branch `case/T2611845`
- Verification checklist

---

## Summary Table

| Step | Script | Agent | AI Calls | Type | Purpose |
|------|--------|-------|----------|------|---------|
| **1** | case-brief | None | 0 | Algorithmic | Scrape data |
| **2** | case-guide | claude-code-guide (TBD) | 1 | Reasoning | Understand problem, create guide |
| **3** | case-solve | case-solver | 2 | Reasoning | Plan changes, apply changes |
| **TOTAL** | — | — | **3 AI calls** | — | — |

---

## Cost & Timing

### Estimated AI Time

- **case-guide** (1 call):
  - Input: 1-3 KB brief
  - Output: 5-15 KB guide
  - Time: 5-10 seconds
  - Tokens: ~2,000-5,000

- **case-solve** (2 calls):
  - Call #1 (plan): 10-30 seconds, ~5,000-10,000 tokens
  - Call #2 (implement): 30-120 seconds, ~10,000-50,000 tokens
  - Total: 1-3 minutes, ~15,000-60,000 tokens

### Total Per Case

- **3 AI calls per case**
- **1.5-3.5 minutes total**
- **17,000-65,000 tokens total**
- **~$0.002-0.008 per case** (with Claude 3.5 Sonnet)

---

## When No AI is Called

These operations are 100% algorithmic:

- ✅ **case-brief** (entire step)
  - Browser scraping
  - REST API queries
  - Markdown compilation

- ✅ **Settings/config management**
  - Storing PAT in Credential Manager
  - Loading/saving config

- ✅ **Health checks**
  - Verifying Python, Git, Claude CLI installed
  - Checking authentication status

- ✅ **Git operations**
  - Cloning repos
  - Creating branches
  - Committing changes

- ✅ **Testing/verification**
  - Running test suites
  - Lint checks
  - Build verification

---

## Customization Points

### Which Agent to Use

**For case-guide:**
```python
# Option 1: Use named agent (if defined in .claude/agents/)
claude -p "Use agent case-guide: ..." 

# Option 2: Use default Claude with custom system prompt
system_prompt = """You are case-guide. Create implementation guides..."""
claude -p --system "$system_prompt" < brief.md
```

**For case-solve:**
```python
# Option 1: Use named agent
claude -p "Use agent case-solver: ..."

# Option 2: Use default Claude
system_prompt = """You are case-solver. Create implementation plans..."""
claude -p --system "$system_prompt" < guide.md
```

### Reducing AI Calls

If cost is a concern:

1. **Skip case-guide** — Use template instead of AI
   - Cost: Save ~2,000-5,000 tokens
   - Quality: Lower (generic vs. problem-specific)

2. **Use cached briefs** — Reuse case-guide output
   - Cost: Save repeated case-guide calls
   - Time: Much faster on reruns

3. **Use simpler model** — Use Claude 3 Haiku instead of Sonnet
   - Cost: 10x cheaper (~$0.0002-0.0008 per case)
   - Quality: Lower (Haiku less capable)

4. **Batch similar cases** — Process 10 cases at once
   - Cost: No reduction, but batching advantages
   - Time: Parallel processing possible

---

## Agent Definitions

Location: `.claude/agents/`

### case-brief.md
- **Type:** Not a Claude agent (reference only)
- **Purpose:** Document the data scraping pipeline
- **Called:** Never (it's algorithmic)

### case-guide.md
- **Type:** Claude agent (or prompt persona)
- **Purpose:** Create implementation guides from briefs
- **Called:** Once per case, in step 2
- **Persona:** Problem analyst, technical writer

### case-solver.md
- **Type:** Claude agent (or prompt persona)
- **Purpose:** Implement changes automatically
- **Called:** Twice per case, in step 3 (plan + apply)
- **Persona:** Code reviewer, architect, implementer

---

## Skills (Reusable Components)

Location: `.claude/skills/`

### extract-context.md
- **Purpose:** Consolidate case data from multiple sources
- **Used by:** case-brief (algorithm follows this pattern)
- **AI-assisted:** No

### generate-plan.md
- **Purpose:** Break guide into actionable steps
- **Used by:** case-solve's first Claude call (plan phase)
- **AI-assisted:** Yes (Claude applies this)

---

## Monitoring AI Usage

To track all AI calls:

```python
# case_guide.py
print(json.dumps({
    "operation": "Calling Claude for guide generation",
    "status": "running",
    "agent": "case-guide",
}))

# case_solve.py (call 1)
print(json.dumps({
    "operation": "Calling Claude for implementation plan",
    "status": "running",
    "agent": "case-solver",
    "phase": "plan",
}))

# case_solve.py (call 2)
print(json.dumps({
    "operation": "Calling Claude to apply changes",
    "status": "running",
    "agent": "case-solver",
    "phase": "apply",
}))
```

The main app captures these and displays them in real-time! 📊

---

## Conclusion

**Total AI calls per case: 3**

- 0 calls in case-brief (algorithmic scraping)
- 1 call in case-guide (create guide from brief)
- 2 calls in case-solve (plan + implement)

**Cost:** ~$0.002-0.008 per case  
**Time:** ~2-4 minutes per case  
**Quality:** High (uses mid-tier Claude for reasoning)

All calls are observable via progress reporting in the UI! ✨
