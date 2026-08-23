# case-wizard Startup Flow

Complete walkthrough of what happens every time the app starts.

## 🚀 Every App Start

```
User runs: python -m streamlit run app/main.py
or double-clicks: run.cmd / run.ps1
                    ↓
            ┌─ App Launches ─┐
            │                │
            ↓                ↓
    Run Health Checks   Load Config
            │                │
            └────────┬────────┘
                     ↓
        Evaluate Health Status
```

---

## 📊 Decision Tree

```
┌──────────────────────────────────────┐
│  Has CRITICAL issues?                │
│  (Python, Git, Claude)               │
└──────────────┬───────────────────────┘
               │
        ┌──────┴──────┐
        │             │
       YES            NO
        │             │
        ↓             ↓
    BLOCK         ┌─────────────────────┐
    Show          │  Config complete?   │
    Fixes         │  (CRM + ADO both ✅)│
                  └─────────┬───────────┘
                            │
                     ┌──────┴──────┐
                     │             │
                    YES           NO
                     │             │
                     ↓             ↓
                  MAIN APP    SETUP FORM
```

---

## 🛑 Scenario 1: Critical Issues Found

```
🧙 case-wizard Setup Verification

Health Checks:
  ✅ Python 3.12.10
  ✅ Git
  ❌ Claude CLI                    ← CRITICAL
  ⚠️ CRM Browser Tab
  ⚠️ Azure DevOps Config

─────────────────────────────────────

❌ Critical Issues Found

You need to fix these before continuing:
  • Claude CLI: Claude CLI not found

─────────────────────────────────────

How to Fix

Install Claude Code:
  1. Go to https://claude.com/claude-code
  2. Download and install for your OS
  3. Run `claude login` in terminal
  4. Return here and refresh

⏳ After fixing, press F5 to refresh and continue.
```

**User action:** Fix issue, press F5 → back to step 1

---

## ⚙️ Scenario 2: Setup Required (Config Incomplete)

```
🧙 case-wizard First-Time Setup

Health Checks:
  ✅ Python 3.12.10
  ✅ Git
  ✅ Claude CLI
  ✅ Claude Logged In
  ⚠️ CRM Browser Tab - Configure in next step
  ⚠️ Azure DevOps Config - Configure in next step

─────────────────────────────────────

Step 2: Configure Your Setup

🌐 Dynamics 365 CRM
App will open CRM, wait for you to log in, then verify

Your CRM URL
[https://artex-crm.crm4.dynamics.com/]

[🔗 Check CRM Login]

User clicks button ↓

🕐 Opening CRM and waiting for login (30 seconds)...

Browser opens → User logs in → App detects → Browser closes

Result:
  ✅ CRM authenticated and ready

─────────────────────────────────────

🔑 Azure DevOps Access
Your organization URL and personal access token

Organization URL
[https://dev.azure.com/myorg_____________]

Personal Access Token
[***PAT_token_here***_________________] [ℹ️ How?]

[🔐 Check ADO Access]

User clicks button ↓

🕐 Testing Azure DevOps API...

App makes API call with credentials

Result option 1 (Success):
  ✅ Connected to myorg

Result option 2 (Failure):
  ❌ Invalid credentials (check PAT and organization)

User can:
  • Click 'ℹ️ How?' to see PAT creation steps
  • Fix values and click 'Check ADO Access' again
  • Repeat until green

─────────────────────────────────────

Once both are GREEN:

[✅ Complete Setup]

Status shown:
  CRM: ✅ Authenticated
  ADO: ✅ Connected to myorg

All green → User clicks "Complete Setup"

↓

Config saved:
  • CRM URL → .streamlit_config.json
  • ADO Org URL → .streamlit_config.json
  • PAT Token → Windows Credential Manager (encrypted)

✅ Setup complete! Restarting app...

↓

App restarts → goes to Scenario 3
```

---

## ✅ Scenario 3: All Green - Go to Main App

```
🧙 case-wizard Setup Verification

Health Checks:
  ✅ Python 3.12.10
  ✅ Git
  ✅ Claude CLI
  ✅ Claude Logged In
  ✅ CRM Browser Tab - Done
  ✅ Azure DevOps Config - Done

All checks pass, configuration complete

↓ (No form shown, no waiting)

🧙 case-wizard

[Case Number: T2611845__________] [🔄 Clear] [❓ Help] [⚙️ Settings]

Brief  |  Guide  |  Solve  |  Status  |  Settings

Brief Tab selected:
  ✅ Brief — Complete

  Inputs:
    Case Number: T2611845
    Source: Dynamics 365 CRM

  Parameters:
    ADO Organization: https://dev.azure.com/myorg
    *Auto-detects project from context*
    💡 Edit parameters in ⚙️ Settings

  [▶ Run Brief]

  Output:
    ℹ️ Not yet run

─────────────────────────────────────

Ready to use!
User can:
  • Enter case number
  • Click "Run Brief"
  • Continue to Guide and Solve tabs
```

---

## 🔄 Subsequent Launches (After Setup)

```
User starts app again

↓

Health checks run (quick, ~2 seconds):
  ✅ Python - passes
  ✅ Git - passes
  ✅ Claude CLI - passes
  ✅ Claude Logged In - passes
  ✅ CRM Browser Tab - marked as done
  ✅ Azure DevOps Config - marked as done

All checks pass, config complete

↓

Main app loads immediately (no setup wizard)

User sees:
  🧙 case-wizard
  [Case Number: _______]

Ready to work!
No delays, no re-entry of secrets
```

---

## 🔧 If User Needs to Change Config Later

```
User in main app

Settings button in top right corner

↓

⚙️ Settings

Normal | Advanced

Normal tab shows:
  
  Dynamics 365
  CRM URL: [https://artex-crm.crm4.dynamics.com/]
  
  Azure DevOps
  Organization URL: [https://dev.azure.com/myorg____]
  PAT: [***token***______________________]
  Stored securely in Windows Credential Manager
  
  Behavior
  ☑ Open results in VS Code
  
  [💾 Save] [🗑️ Clear Secrets]

User can:
  • Edit any field
  • Click "💾 Save"
  • Changes take effect immediately
  
  OR
  
  • Click "🗑️ Clear Secrets"
  • Resets all config
  • Next launch shows setup wizard again
```

---

## 📋 Status Indicators

### Health Check Statuses

```
✅ Green = Working, no action needed
❌ Red = Broken, must fix to continue
⚠️ Yellow = Warning, can continue but needs attention
```

### Setup Form Statuses

```
CRM Status:
  (none) = Not checked yet
  ⏳ = Checking...
  ✅ = Authenticated
  ❌ = Failed, can retry

ADO Status:
  (none) = Not checked yet
  🕐 = Testing...
  ✅ = Connected
  ❌ = Failed, can retry

Submit Button:
  Disabled if: CRM not ✅ or ADO not ✅
  Enabled if: Both CRM and ADO are ✅
```

---

## 🎯 Perfect User Experience

| Situation | What Happens | User Action |
|-----------|--------------|-------------|
| **First Launch** | Show setup form with health checks | Enter CRM URL, click Check → Enter ADO creds, click Check → Complete Setup |
| **Second Launch** | All green, skip to main app | Start working immediately |
| **System broken** | Show critical error with fix | Follow fix steps, refresh |
| **Want to change creds** | Go to Settings tab | Edit and Save |
| **Want to reset** | Click "Clear Secrets" | Next launch shows setup again |

---

## ✨ Why This Works

✅ **Transparency** — User always sees what's ✅ and what's ❌
✅ **Immediate feedback** — Buttons show results right away
✅ **Self-healing** — User can fix issues without leaving app
✅ **No surprises** — Validates everything before running cases
✅ **Reusable credentials** — Saved and remembered automatically
✅ **No manual steps** — Everything in UI, no terminal commands
✅ **Fast subsequent launches** — Health checks transparent when OK

---

## 🚀 Result

**Every launch:**
1. ✅ Check system health
2. ✅ Show what needs attention
3. ✅ Let user fix in situ
4. ✅ Recheck automatically
5. ✅ When all green → go to app

**No confusion, no surprises, no manual steps!** 🎉
