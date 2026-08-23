# Troubleshooting Guide

## Preflight Checks Failing

### Python 3.8+
**Error:** "Python not found" or "Python version too old"
**Fix:**
1. Download from https://python.org
2. Install, check "Add to PATH"
3. Restart terminal
4. Verify: `python --version`

### Git
**Error:** "Git not found"
**Fix:**
1. Download from https://git-scm.com
2. Install with defaults
3. Restart terminal
4. Verify: `git --version`

### Claude CLI
**Error:** "Claude not found" or "Claude not installed"
**Fix:**
1. Download from https://claude.com/claude-code
2. Install for your OS
3. Restart terminal
4. Verify: `claude --version`

### Claude Login
**Error:** "Not logged in" or "Not responding to prompts"
**Fix:**
1. Run: `claude login`
2. Browser opens for authentication
3. Complete sign-in
4. Return to case-wizard
5. Click [↻ Recheck All]

---

## Service Checks Failing

### CRM Login
**Error:** ❌ Not logged in / Access denied

**What happened:**
- CRM URL configured but you're not logged in
- Browser session expired
- Network can't reach CRM

**How to fix:**
1. Open CRM URL in your browser
2. Log in with your credentials
3. Keep tab open
4. Return to case-wizard
5. Click [↻ Recheck CRM]

---

### Azure DevOps (ADO) API
**Error:** ❌ Invalid credentials / Access denied / Connection failed

**What happened:**
- PAT token is wrong or expired
- Organization URL is incorrect
- Network can't reach Azure DevOps
- PAT scopes are insufficient

**How to fix:**
1. Check organization URL: https://dev.azure.com/yourorg
2. Check PAT is not expired (valid 1 year max)
3. Verify PAT has these scopes:
   - ✅ Code (Read)
   - ✅ Project and Team (Read)
4. If PAT expired:
   - Go to: https://dev.azure.com/yourorg/_usersSettings/tokens
   - Delete old PAT
   - Create new PAT with same scopes
5. Update in Settings tab
6. Click [↻ Recheck ADO]

---

## Stage Failures

### Brief Fails
**"Brief generation failed" or "CRM data not found"**

**Possible causes:**
1. CRM tab not logged in
2. CRM tab not open when Brief runs
3. Case number doesn't exist in CRM
4. Network timeout

**How to fix:**
1. Verify CRM is still logged in (check browser tab)
2. Close CRM tab and reopen to refresh
3. Verify case number exists in CRM
4. Try [↻ Recheck CRM] first
5. Click [▶ Run Brief] again

---

### Guide Fails
**"Claude API error" or "Guide generation failed"**

**Possible causes:**
1. Claude not responding
2. Network issue
3. Claude session expired

**How to fix:**
1. Try [↻ Recheck All] first
2. If Claude shows ❌:
   - Run: `claude login` again
   - Return to case-wizard
   - Click [↻ Recheck All]
3. Try [▶ Run Guide] again

---

### Solve Fails
**"Repository clone failed" or "Implementation failed"**

**Possible causes:**
1. Repo URL wrong
2. Git credentials not cached
3. Network timeout
4. Branch already exists
5. Insufficient permissions

**How to fix:**
1. Verify repo URL is correct and accessible
2. If git asks for credentials:
   - Use your GitHub/ADO username
   - Use PAT or personal access token (not password)
3. Check network connection
4. Try [▶ Run Solve] again with a different case number

---

## Can't Log Into CRM
**"Browser won't load CRM" or "Login page loops"**

**What to check:**
1. Is CRM URL correct? Check in Settings
2. Is your account active in CRM?
3. Do you have access to this organization?
4. Try different browser or incognito mode
5. Clear browser cookies for CRM domain

**If still stuck:**
1. Contact your CRM administrator
2. Verify your user account has CRM access
3. Check if 2FA is enabled and working

---

## Can't Create ADO PAT
**"Token creation page won't load" or "Can't see options"**

**URL should be:**
```
https://dev.azure.com/yourorg/_usersSettings/tokens
```

**If page won't load:**
1. Verify you're logged into ADO
2. Check organization URL is correct
3. Try different browser
4. Clear ADO cookies and refresh

**Can't see "New Token" button:**
1. You may not have permission
2. Contact your ADO administrator
3. Ask them to create a PAT for you

---

## Network/Firewall Issues
**"Can't reach CRM" or "ADO API timeout"**

**Possible causes:**
1. Firewall blocking access
2. VPN required but not connected
3. Network down
4. Corporate proxy interfering

**How to fix:**
1. Check if VPN is needed (ask your IT)
2. Connect VPN if required
3. Try different network (home wifi vs office)
4. Check firewall rules
5. Ask IT if URLs are whitelisted:
   - `*.dynamics.com`
   - `dev.azure.com`

---

## Still Stuck?

If you've tried everything above:

1. **Verify Preflight shows all green** 🛫
2. **Check CRM and ADO services are reachable**
3. **Try [↻ Recheck All] button**
4. **Restart the app** and try again
5. **Contact support** with error message

---

## Quick Links

- **CRM:** https://apps.dynamics.com
- **ADO:** https://dev.azure.com/yourorg
- **Claude Login:** Run `claude login` in terminal
- **Create PAT:** https://dev.azure.com/yourorg/_usersSettings/tokens
