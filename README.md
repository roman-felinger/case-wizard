# case-wizard

**Automate support cases: brief → guide → implement.**

Three-stage automation that turns a support case into a committed feature branch.

```
Brief (gather context) → Guide (AI walkthrough) → Solve (auto-implement)
```

## Quick Start

**Windows:** Double-click `run.cmd`  
**Mac/Linux:** `./run.sh`  
**Python:** `python -m streamlit run app/main.py`

First run installs dependencies (~30 sec), then opens at `http://localhost:8501`.

## The Three Stages

### 1. case-brief
Gather case context from CRM, Azure DevOps, Business Central.  
Output: `case-briefs/case-<number>.md`

### 2. case-guide
Turn brief into a step-by-step walkthrough using Claude.  
Output: `case-guides/case-<number>-for-dummies.md`

### 3. case-solve
Auto-implement changes, run tests, create commits, verify.  
Output: `case-solves/<number>/VERIFICATION_CHECKLIST.md`

## Requirements

- Python 3.8+
- Dynamics 365 CRM (with browser tab open)
- Azure DevOps PAT in `AZDO_PAT` env var
- Claude API key in `CLAUDE_API_KEY` env var

## Configuration

Create `config.json` in each stage directory (see `config.example.json`).

Each stage also supports CLI flags (`-h` to see all).

## Manual Run

```bash
# One at a time:
cd case-brief && python case_brief.py T2611845
cd ../case-guide && python case_guide.py T2611845
cd ../case-solve && python case_solve.py T2611845

# Or use the desktop app (recommended)
python -m streamlit run app/main.py
```

## Status

- ✅ Brief: CRM + ADO working, BC selectors in progress
- ✅ Guide: Stable, requires Claude API key
- ✅ Solve: Stable, auto-detects repo structure
- ✅ Desktop app: Streamlit UI, simple and fast

## License

See LICENSE file.
