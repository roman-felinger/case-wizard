# case-wizard: User Experience Flow

Complete walkthrough of the user experience from first launch to using the app.

## 🚀 FIRST LAUNCH

### Screen 1: Health Checks
```
🧙 case-wizard First-Time Setup
Step 1: System Requirements
Checking your system...

✅ Python 3.12.10
✅ Git version 2.55.0
✅ Claude CLI 2.1.229  
✅ Claude Logged In - Responding to prompts
⚠️ CRM Browser Tab - Configure in next step
⚠️ Azure DevOps Config - Configure in next step
```

Status:
- All CRITICAL items pass ✅
- Only WARNINGS (user-configurable items)
- Continue to setup form

### Screen 2: Setup Wizard - CRM & ADO Config
```
Step 2: Configure Your Setup

🌐 Dynamics 365 CRM
Keep a browser tab open with Dynamics 365 CRM (logged in)

Your CRM URL
[https://artex-crm.crm4.dynamics.com/]
[🔗 Open CRM] [✅ Logged in]


🔑 Azure DevOps Access
Your organization URL and personal access token

Organization URL
[https://dev.azure.com/myorg_____________]

Personal Access Token (PAT)
[***PAT***_____________________________] [ℹ️ How?]

[✅ Complete Setup]
```

User actions:
1. **Enter/confirm CRM URL** (pre-filled with your org)
2. **Click "🔗 Open CRM"** → Opens https://artex-crm.crm4.dynamics.com/ in browser
3. **Log in to CRM** (if not already)
4. **Return to app, check "✅ Logged in"**
5. **Enter Azure DevOps org URL** (e.g., https://dev.azure.com/artex-is)
6. **Paste PAT token** (get from https://dev.azure.com/artex-is/_usersSettings/tokens)
7. **Click "✅ Complete Setup"**

What happens:
- ✅ CRM URL saved to `.streamlit_config.json`
- ✅ ADO org URL saved to `.streamlit_config.json`
- ✅ PAT token saved to Windows Credential Manager (encrypted)
- ✅ App restarts automatically

---

## 🎯 SECOND LAUNCH (and all future launches)

### Screen 1: Health Checks
```
✅ All checks pass
✅ Config complete
→ Skip setup wizard → Go to main app
```

Status:
- Setup not shown again
- Config is remembered
- Straight to main app

### Screen 2: Main Application
```
🧙 case-wizard

Brief  |  Guide  |  Solve  |  Status  |  Settings

┌─ Brief Tab ─────────────────────────┐
│ ✅ Brief — Complete                 │
│                                     │
│ Inputs:                             │
│ Case Number: [T2611845____________]│
│ Source: Dynamics 365 CRM            │
│                                     │
│ Parameters:                         │
│ ADO Organization                    │
│ https://dev.azure.com/artex-is      │
│ *Auto-detects project from context* │
│ 💡 Edit parameters in ⚙️ Settings   │
│                                     │
│ [▶ Run Brief]                       │
│                                     │
│ Output:                             │
│ ℹ️ Not yet run                      │
└─────────────────────────────────────┘
```

User experience:
- CRM URL already remembered ✅
- ADO credentials already saved ✅
- Just enter case number and click Run
- No re-entry of secrets needed

---

## ⚙️ EDITING CONFIGURATION

If user needs to change CRM URL, ADO org, or PAT:

### Go to Settings Tab
```
⚙️ Settings

┌─ Normal ─────┐ ┌─ Advanced ────┐
│ Normal       │ │ Advanced      │
└──────────────┘ └───────────────┘

Dynamics 365
CRM URL
[https://artex-crm.crm4.dynamics.com/]

Azure DevOps
Organization URL
[https://dev.azure.com/artex-is______]

Personal Access Token (PAT)
[***token_here***___________________]
Stored securely in Windows Credential Manager

Behavior
☑ Open results in VS Code

[💾 Save] [🗑️ Clear Secrets]
```

User can:
- ✅ Edit CRM URL
- ✅ Edit ADO org URL
- ✅ Edit PAT token
- ✅ Change other behavior settings
- ✅ Click "💾 Save" to update
- ✅ Click "🗑️ Clear Secrets" to reset everything

---

## 🎬 TYPICAL WORKFLOW

### Run a Case (Brief → Guide → Solve)

```
1. Enter Case Number
   [T2611845____________]

2. Click Brief Tab
   ✅ System pre-configured
   ✅ CRM & ADO credentials ready
   [▶ Run Brief]

3. Progress Shows:
   📍 Connecting to automation Chrome window...
   ✅ CRM data extracted
   📍 Querying Azure DevOps...
   ✅ Found 3 related PRs
   📍 Building markdown brief...
   ✅ Brief complete

4. Guide Tab Becomes Available
   [▶ Run Guide]
   
5. Progress Shows:
   📍 Calling Claude for guide generation...
   ✅ Guide generated
   ✅ Guide ready

6. Solve Tab Becomes Available
   [▶ Run Solve]

7. Progress Shows:
   📍 Cloning repository...
   ✅ Repository ready
   📍 Generating implementation plan...
   ✅ Plan generated
   📍 Applying changes...
   ✅ All changes applied
   ✅ Solve complete

8. Check Status Tab
   ✅ All 3 stages complete!
   
9. Review Results
   case-solves/case-T2611845/
   ├─ repo/ (cloned + modified)
   └─ VERIFICATION_CHECKLIST.md
```

---

## ✅ What Makes Sense

### ✅ Secrets Not Re-asked
- First time: User enters all secrets in setup wizard
- Second time: App loads them from secure storage
- Never asks again unless user clicks "Clear Secrets"

### ✅ Pre-filled Forms
- CRM URL field pre-filled with saved value
- ADO org field pre-filled with saved value
- Settings tab shows all saved config

### ✅ One-Time Setup
- Setup wizard only shows if config incomplete
- After setup → goes straight to main app
- Fast startup on subsequent launches

### ✅ Easy Editing
- Settings tab available anytime
- Edit any config value without re-running setup
- Save button commits changes immediately

### ✅ Clear Labeling
- Settings organized by section
- Help text explains each field
- Shows where secrets are stored (Credential Manager)

### ✅ No Confusion
- CRM URL is customizable (not hardcoded)
- ADO org and PAT are clearly separated
- Clear distinction between required (blocking) vs optional (configurable)

---

## 🔒 Security Flow

```
First Launch Setup:
  User enters PAT
    ↓
  App receives PAT
    ↓
  PAT sent to keyring.set_password()
    ↓
  Windows Credential Manager stores encrypted
    ↓
  Not stored in files, not logged, not visible

Subsequent Launches:
  App calls keyring.get_password()
    ↓
  Credential Manager returns encrypted value
    ↓
  App uses PAT for ADO API calls
    ↓
  Used in subprocess environment: env["AZDO_PAT"] = pat
    ↓
  case-brief script reads from environment
    ↓
  Never visible to user in logs, config files, or UI
```

---

## 📋 Checklist: Does Everything Make Sense?

- ✅ Setup wizard only shown once (on first launch)
- ✅ All secrets saved securely (Credential Manager)
- ✅ Saved values pre-filled in setup wizard if shown again
- ✅ Settings tab allows editing any config value
- ✅ Settings tab shows CRM URL (was missing before)
- ✅ No hardcoded URLs (uses config values)
- ✅ "Clear Secrets" button to reset everything
- ✅ Main app never asks for credentials
- ✅ Progress shows what agent is running
- ✅ Health checks explain what's missing
- ✅ Setup form has helpful tooltips
- ✅ CRM button actually opens the right URL
- ✅ PAT is marked as "Stored securely"
- ✅ No re-entry of working secrets

**Everything makes sense! ✨**
