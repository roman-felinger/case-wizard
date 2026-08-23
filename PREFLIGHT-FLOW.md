# Preflight Flow: One-Time Setup

The Preflight is the **only setup screen needed**. Everything else is optional settings.

## First Launch

```
App starts
    ↓
Preflight shows: "Setup Required"
    ↓
🛫 PREFLIGHT SETUP (Required)

  System Checks (auto-verified):
    ✅ Python 3.8+
    ✅ Git  
    ✅ Claude CLI
    ✅ Claude Logged In

  Service Configuration (user enters):
    🌐 CRM URL:
    [https://artex-crm.crm4.dynamics.com/]
    [🔗 Open CRM] [↻ Verify CRM Login]
    Status: ✅ Logged in

    🔑 ADO Organization URL:
    [https://dev.azure.com/myorg_______]
    
    🔑 ADO Personal Access Token:
    [***PAT_here***__________________]
    [ℹ️ How to create] [↻ Verify ADO API]
    Status: ✅ Connected

  [✅ Setup Complete] ← Only enabled when ALL tests pass

    ↓
    (User fills in fields, clicks individual verify buttons)
    (All tests pass)
    ↓

✅ ALL CHECKS PASS
Config saved → No more setup needed!
```

## Subsequent Launches

```
App starts
    ↓
Preflight shows: Quick Status Bar
    ✅ Python  ✅ Git  ✅ Claude  ✅ Claude Login
    ✅ CRM  [↻ Recheck]  ✅ ADO  [↻ Recheck]
    [↻ Recheck All]
    ↓
All green? → Go straight to main app
Anything red? → Expand preflight, show fix options
```

## Design Principles

✅ **First time**: Setup is unavoidable but straightforward (5 minutes)
✅ **Every other time**: Just verify all working (< 1 second if green)
✅ **If broken**: One button to fix, no guessing
✅ **Settings tab**: For tweaks only, not required for basic use

## Never Ask User For

❌ Project/repository URLs (auto-detect or ask per case)
❌ Case numbers upfront (ask when running Brief)
❌ Testing preferences (defaults: skip for speed)
❌ Advanced options (hide until user needs them)

## What Preflight Tests

| Check | When | How |
|-------|------|-----|
| Python | First launch + startup | Run `python --version` |
| Git | First launch + startup | Run `git --version` |
| Claude CLI | First launch + startup | Run `claude --version` |
| Claude Login | First launch + startup | Run `claude -p` with test prompt |
| CRM Login | First setup + on click | HTTP request to CRM URL |
| ADO API | First setup + on click | API call with PAT credentials |

## User Experience Timeline

```
Minute 1: User opens app
  ↓
Minute 2: Downloads/installs Claude Code, logs in
  ↓
Minute 3: Opens app again, enters CRM URL and ADO credentials
  ↓
Minute 4: Clicks verify buttons, all pass
  ↓
Minute 5: [✅ Setup Complete] enabled, clicks it
  ↓
Config saved, ready to use!
Never see setup again unless config deleted.
```

## After Setup Is Done

User just:
1. Enters case number
2. Clicks "Run Brief"
3. Checks "Run Guide" 
4. Checks "Run Solve"
5. Reviews outputs

No configuration, no settings, no setup. Just work!

## If Something Breaks Later

Example: ADO PAT expires

```
App starts
  ↓
Preflight shows:
  ✅ CRM  [↻ Recheck]
  ❌ ADO  [↻ Recheck]
  
  ❌ ADO: Invalid credentials
  
  [Fix: Go to Settings or paste new PAT here]
  ↓
User pastes new PAT, clicks [↻ Recheck ADO]
  ↓
✅ ADO: Connected
  ↓
Preflight collapses, back to work
```

## Settings Tab

For users who want to tweak:
- Run tests during Solve (default: skip)
- Run lint (default: skip)
- Change Claude model
- Change timeouts

**But none of this is required.** Defaults work for 99% of use cases.

## Summary

**Preflight = Complete one-time setup**
- Tests everything
- No more wizards
- Settings tab for tweaks only
- User runs tool → preflight quick checks → gets to work
