# case-wizard Web Dashboard

Beautiful React-based web interface for the case-wizard automation suite.

## Quick Start

```powershell
# One command to start everything
.\start-web.ps1

# Opens: http://localhost:3000
```

That's it! The dashboard will:
- Start Flask backend on port 5000
- Start React frontend on port 3000
- Auto-open in your browser

## Features

### 🎨 Beautiful Interface
- Dark mode optimized design
- Real-time progress visualization
- Animated pipeline stages
- Responsive layout (mobile-friendly)

### 🚀 Real-Time Updates
- WebSocket connection for live updates
- Watch each stage progress in real-time
- Live output logs from each stage
- Status indicators for each phase

### 📊 Three-Stage Pipeline
Visually shows:
1. **Gather Brief** — CRM, ADO, BC context collection
2. **Generate Guide** — Claude-powered guide writing
3. **Auto-Implement** — Automated implementation + verification

### 📋 Case Input Form
- Simple case number entry
- Real-time validation
- Quick start button
- What-happens explanation

### 📈 Results Display
After completion:
- Brief preview
- Guide preview
- Verification checklist link
- Status summary

## How It Works

```
┌─────────────────────────────────────┐
│    User opens browser               │
│    http://localhost:3000            │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    React Frontend (Vite)            │
│    - Case input form                │
│    - Pipeline visualization         │
│    - Real-time status updates       │
└──────────────┬──────────────────────┘
               │ WebSocket
               │ REST API
               ▼
┌─────────────────────────────────────┐
│    Flask Backend                    │
│    - Workflow orchestration         │
│    - Subprocess management          │
│    - File serving                   │
└──────────────┬──────────────────────┘
               │ Subprocesses
               ▼
┌─────────────────────────────────────┐
│    Python Scripts                   │
│    - case-brief.py                  │
│    - case-guide.py                  │
│    - case-solve.py                  │
└─────────────────────────────────────┘
```

## Architecture

### Backend (Flask)
- **app.py** — Main Flask app, WebSocket server
- **REST endpoints:**
  - `POST /api/workflow/start` — Start a workflow
  - `GET /api/workflow/{id}/status` — Get workflow status
  - `GET /api/results/{case_number}` — Get results
  - `GET /api/health` — Health check
- **WebSocket events:**
  - `workflow_update` — Stage progress updates
  - `workflow_complete` — Workflow finished

### Frontend (React + Vite)
- **src/App.jsx** — Main app component, WebSocket setup
- **src/components/CaseInput.jsx** — Case form
- **src/components/WorkflowDashboard.jsx** — Pipeline visualization
- **src/components/StageCard.jsx** — Individual stage display
- **src/components/LogViewer.jsx** — Log output viewer
- **Styling:** Tailwind CSS + custom CSS

## Requirements

### Minimal Setup
- **Python 3.8+** (for backend and case scripts)
- **Node.js 16+** with npm (for frontend)
- **Git** (to clone repos)

That's it! No Docker required, no complex dependencies.

### Installation

Already handled by `start-web.ps1`, but manual setup:

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py

# Frontend (in new terminal)
cd frontend
npm install
npm run dev
```

## Usage

### Starting a Workflow

1. Open http://localhost:3000
2. Enter a case number (e.g., `T2611845`)
3. Click "Start Automation"
4. Watch the pipeline execute:
   - Brief collection
   - Guide generation
   - Implementation & verification
5. Review results when complete

### Monitoring Progress

- Each stage shows:
  - Real-time status (pending → running → complete/error)
  - Progress bar
  - Live output logs (expandable)
- Visual feedback:
  - Spinning loader for active stage
  - Green checkmark for completed stages
  - Red X for errors

### Accessing Results

After a workflow completes:
- **Brief:** `case-brief/case-briefs/case-<number>.md`
- **Guide:** `case-guide/case-guides/case-<number>-for-dummies.md`
- **Checklist:** `case-solve/case-solves/case-<number>/VERIFICATION_CHECKLIST.md`

Links are provided in the dashboard.

## Customization

### Change Port Numbers

Edit `vite.config.js` (frontend port) and `app.py` (backend port):

```javascript
// vite.config.js
server: {
  port: 3000,  // Change this
}

// app.py
socketio.run(app, ..., port=5000)  # Change this
```

### Add Environment Variables

Create `.env` in frontend or backend:

```
VITE_API_URL=http://localhost:5000
VITE_WS_URL=ws://localhost:5000
```

### Styling

Tailwind CSS classes — edit `tailwind.config.js` for colors, fonts, theme.

## Troubleshooting

### "Port already in use"
```powershell
# Find process on port 3000
netstat -ano | findstr :3000

# Kill it
taskkill /PID <PID> /F
```

### "Cannot find module 'socket.io-client'"
```powershell
cd frontend
npm install socket.io-client
```

### Backend connection fails
```powershell
# Check backend is running
curl http://localhost:5000/api/health

# Restart both services
.\start-web.ps1
```

### WebSocket connection timeout
- Check firewall (ports 3000, 5000)
- Make sure backend is running
- Browser console (F12) shows WebSocket errors

## Performance

- **Frontend:** Vite (instant HMR, very fast)
- **Backend:** Flask + SocketIO (lightweight, async)
- **Total:** ~150MB disk, <50MB memory usage

## Next Steps

- ✅ Run `.\start-web.ps1`
- ✅ Visit http://localhost:3000
- ✅ Enter a case number and start a workflow
- ✅ Watch it execute in real-time
- ✅ Review results

## Development

### Add a new component

```jsx
// src/components/MyComponent.jsx
export default function MyComponent() {
  return <div>Hello</div>
}

// In App.jsx or other file:
import MyComponent from './components/MyComponent'
```

### Add a new API endpoint

```python
# backend/app.py
@app.route("/api/my-endpoint", methods=["GET"])
def my_endpoint():
    return jsonify({"data": "hello"})
```

### Update styling

Edit `src/index.css` or Tailwind classes in JSX components.

---

**That's it!** A beautiful, responsive, real-time web dashboard for case automation.

Enjoy! 🚀
