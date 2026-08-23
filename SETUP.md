# case-wizard Setup & Health Checks

When you first run case-wizard, it checks everything you need to run successfully and guides you through setup.

## What Gets Checked

The setup wizard runs **6 health checks**:

### Step 1: System Requirements (CRITICAL)

These must be installed. Setup shows how to fix each one:

| Check | Status | What It Does | If Missing |
|-------|--------|-------------|-----------|
| **Python 3.8+** | ❌ CRITICAL | Checks Python is installed and ≥3.8 | Download from python.org, add to PATH |
| **Git** | ❌ CRITICAL | Checks git is installed | Download from git-scm.com, restart terminal |
| **Claude CLI** | ❌ CRITICAL | Checks Claude Code is installed | Download from claude.com/claude-code |
| **Claude Logged In** | ❌ CRITICAL | Runs test prompt: "Say 'OK'" | Run `claude login` in terminal |

If ANY of these fail, setup blocks you and shows exact fix steps.

### Step 2: Configuration (Guided Setup)

Once system requirements are met, setup prompts you to configure:

| Check | Status | What It Does | What You Do |
|-------|--------|-------------|-----------|
| **CRM Browser Tab** | ⚠️ WARNING | Requires Dynamics 365 open+logged in | Click "🔗 Open CRM" button, log in, check ✅ |
| **Azure DevOps Config** | ❌ BLOCKS | Requires org URL + PAT token | Enter org URL, paste PAT, use "ℹ️ How?" helper |

## The Setup Flow

### First Launch
```
1. Health checks run automatically
2. Shows status of all 6 checks
   ✅ Python 3.8+
   ✅ Git
   ✅ Claude CLI
   ✅ Claude Logged In
   ⚠️  CRM Browser Tab
   ❌ Azure DevOps Config
```

### If System Tools Missing
```
Setup blocks with "Critical Issues Found"
Shows: "Install Python 3.8+" → Links to python.org
Or:    "Install Git" → Links to git-scm.com
Or:    "Install Claude Code" → Links to claude.com/claude-code
Or:    "Run: claude login" → Instructions in terminal

User fixes, presses F5, returns to setup
```

### If System Tools OK But Config Missing
```
Setup shows "Step 2: Configure Your Setup"

🌐 Dynamics 365 CRM
   [🔗 Open CRM] [✅ Logged in to CRM]
   
🔑 Azure DevOps Access
   Organization URL: [https://dev.azure.com/myorg    ]
   Personal Access Token: [***PAT here***] [ℹ️ How?]
   
⚠️  CRM Browser Tab: Requires Dynamics 365 tab (open + logged in)

[✅ Complete Setup] [❌ Exit]
```

### After Setup Complete
```
Configuration saved to:
  - PAT: Windows Credential Manager (encrypted)
  - URL: Local .streamlit_config.json

App restarts → Main interface appears → Ready to use!
```

## Configuration Storage

Secrets are kept safe:

| Item | Stored In | Notes |
|------|-----------|-------|
| **Azure DevOps PAT** | Windows Credential Manager | Encrypted by OS |
| **Organization URL** | `.streamlit_config.json` | Local file (not sensitive) |
| **Claude Login** | System's `claude` command | Handled by Claude Code |

No secrets in code, no API keys in environment.

## What Happens If Setup Fails

### System Tool Blocks (Python/Git/Claude)
- ❌ Setup **stops completely**
- Shows exact instructions to install
- Links to official download pages
- User must fix and restart

### Configuration Blocks (CRM/AZDO)
- ❌ Setup **requires** all fields
- Shows validation error: "Please fill in all required fields"
- User fixes and clicks "✅ Complete Setup" again
- Saves on success and restarts

## Running Without Setup

If setup is complete, it's skipped on subsequent runs.

To **re-run setup**, clear configuration:
```python
# In app, go to Settings tab:
Clear All Settings → This resets config and health checks
```

To **manually edit**, go to Settings tab:
- Normal Settings: org URL
- Advanced Settings: tests/lint/build/timeout
- Change and click Save

## Troubleshooting

**"Claude CLI not found"**
- Install Claude Code: https://claude.com/claude-code
- Restart terminal
- Verify: `claude --version`

**"Claude not logged in"**
- Run: `claude login`
- Browser opens, authenticate
- Return to case-wizard

**"CRM login failed"**
- Check: Browser tab is at https://apps.dynamics.com
- Check: You're logged in (not just visiting)
- Keep tab open during Brief runs

**"Azure DevOps failed"**
- Check: PAT is correct (copied fully)
- Check: PAT has "Code (Read)" scope
- Check: PAT has "Project and Team (Read)" scope
- Create new PAT if needed

## Next Steps

Once setup completes:

1. **Enter case number** (e.g., T2611845) in Brief tab
2. **Click ▶ Run Brief** to start
3. See Guide and Solve tabs once data is ready

All requirements are auto-verified before each run. No manual setup after first time! ✨
