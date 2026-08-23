# case-wizard: Desktop App

Simple, standalone desktop application. No web server management, no background processes.

**Just click an icon and it runs.**

## Quick Start

### Windows
Double-click: **`run.cmd`**

### macOS / Linux
```bash
./run.sh
```

Or with Python directly:
```bash
python run.ps1
```

That's it! The app will:
1. ✅ Install dependencies (first time only, ~30 seconds)
2. ✅ Start automatically
3. ✅ Open in your browser at http://localhost:8501
4. ✅ Close when you close the terminal

## What You Get

A clean, simple interface:

```
┌────────────────────────────────────────────────┐
│  🧙 case-wizard                                │
│  Three-stage automation for support cases      │
├────────────────────────────────────────────────┤
│                                                │
│  START A CASE                 PIPELINE STATUS │
│  ─────────────                ──────────────  │
│  Case Number: [T2611845]      📋 Gather Brief │
│                               📖 Generate Guide│
│  [▶ Start] [🔄 Clear]         ⚙️ Auto-Implement│
│                                                │
│                               (Live updates as│
│                                stages execute)│
│                                                │
├────────────────────────────────────────────────┤
│  case-wizard v2.0 | GitHub                    │
└────────────────────────────────────────────────┘
```

## How It Works

1. Enter a case number (e.g., `T2611845`)
2. Click "▶ Start"
3. Watch three stages execute in real-time:
   - 📋 **Gather Brief** — CRM, ADO, BC context
   - 📖 **Generate Guide** — Claude-powered walkthrough
   - ⚙️ **Auto-Implement** — Changes + verification
4. See results when complete

No clicking between tabs, no managing background processes. Everything happens right in front of you.

## Architecture

```
Your Computer
│
├─ run.cmd / run.sh / run.ps1 (startup script)
│  │
│  ├─ Creates Python virtual environment (.venv/)
│  ├─ Installs Streamlit + dependencies
│  └─ Starts: streamlit run app/main.py
│
└─ Streamlit App (app/main.py)
   │
   ├─ Starts local web server (http://localhost:8501)
   ├─ Opens browser automatically
   └─ Runs your Python scripts:
      ├─ case-brief.py
      ├─ case-guide.py
      └─ case-solve.py
```

**That's it.** No external servers, no background processes to manage, no web server configuration.

## Why Streamlit?

✅ **Minimal Setup**
- One command to run
- No configuration needed
- Auto-installs dependencies

✅ **Built-in Server**
- Starts automatically
- Closes when you quit
- No port conflicts (uses 8501 by default)

✅ **Beautiful UI**
- Clean, modern design
- Responsive layout
- Works on any browser

✅ **Live Updates**
- Real-time progress tracking
- Expandable output logs
- Status indicators

✅ **Self-Contained**
- Everything runs locally
- No internet needed
- No external dependencies

## Requirements

- **Python 3.8+** (already on most systems)
- That's it!

No Node.js, no Docker, no complex setup.

## Usage

### First Time
```powershell
# Windows: Just double-click
run.cmd

# macOS/Linux:
./run.sh
```

Takes ~30 seconds to install dependencies, then opens automatically.

### Every Other Time
Same thing — just run the script. Streamlit detects changes and reloads automatically.

### Creating Cases

1. **Enter case number:** `T2611845`
2. **Click Start**
3. **Watch progress:**
   - Each stage shows status (🔄 Running, ✅ Complete, ❌ Error)
   - Logs are expandable for details
4. **See results** in output messages with file paths

### Output

Results go to the same places as before:
- `case-brief/case-briefs/case-<number>.md`
- `case-guide/case-guides/case-<number>-for-dummies.md`
- `case-solve/case-solves/case-<number>/VERIFICATION_CHECKLIST.md`

Links are shown in the app.

## Customization

### Change Port
Edit `app/main.py`:
```python
# Default is 8501, can be any port
streamlit run app/main.py --server.port 8000
```

### Dark/Light Mode
Streamlit auto-detects your system theme. Override in `~/.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#3B82F6"
backgroundColor = "#0F172A"
secondaryBackgroundColor = "#1E293B"
textColor = "#CBD5E1"
```

### Advanced Config
See [Streamlit config docs](https://docs.streamlit.io/library/advanced-features/configuration)

## Troubleshooting

### "Port 8501 already in use"
```powershell
# Find process
netstat -ano | findstr :8501

# Kill it
taskkill /PID <PID> /F

# Then run again
```

Or Streamlit automatically tries the next port (8502, 8503, etc).

### "Python not found"
Install from https://python.org and add to PATH.

### "pip install failed"
```powershell
# Try with explicit path
C:\Python311\python.exe -m pip install -r app/requirements.txt
```

### Browser doesn't open
Manually visit: http://localhost:8501

## Creating a Desktop Shortcut (Windows)

1. Right-click on `run.cmd`
2. "Send to" → "Desktop (create shortcut)"
3. Right-click shortcut → "Properties"
4. Change icon: click "Change Icon", browse to a .ico file
5. Double-click shortcut to run app

## Creating an App Icon (Optional)

To make it look more professional, create a `.ico` file and reference it in the shortcut.

Or use a tool like **Nuitka** or **PyInstaller** to create a standalone .exe (advanced, optional).

For most users, just use `run.cmd` — it's simple and it works.

## Performance

- **Startup:** ~3 seconds (after first install)
- **Memory:** ~50-100MB while running
- **Disk:** ~100MB (Python venv + Streamlit)

Minimal footprint. Runs smoothly on any modern computer.

## Deployment

Want to run on another machine?
1. Copy the `case-wizard` folder
2. Run `run.cmd` (Windows) or `run.sh` (Mac/Linux)
3. Done!

No installation needed. Just works.

---

**That's the vision:** Click an icon, app opens, do your work, close the window when done.

No servers, no background processes, no complexity. Just a simple, beautiful tool.

Enjoy! 🧙
