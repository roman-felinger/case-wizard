import { useState, useEffect } from 'react'
import { io } from 'socket.io-client'
import WorkflowDashboard from './components/WorkflowDashboard'
import CaseInput from './components/CaseInput'
import './App.css'

export default function App() {
  const [socket, setSocket] = useState(null)
  const [activeWorkflow, setActiveWorkflow] = useState(null)
  const [workflows, setWorkflows] = useState({})

  // Initialize WebSocket connection
  useEffect(() => {
    const newSocket = io('http://localhost:5000', {
      transports: ['websocket', 'polling'],
    })

    newSocket.on('connect', () => {
      console.log('Connected to backend')
    })

    newSocket.on('workflow_update', (data) => {
      setWorkflows(prev => ({
        ...prev,
        [data.case_number]: {
          ...prev[data.case_number],
          lastUpdate: new Date(),
          stage: data.stage,
          status: data.status
        }
      }))
    })

    newSocket.on('workflow_complete', (data) => {
      console.log('Workflow complete:', data)
    })

    setSocket(newSocket)

    return () => {
      newSocket.close()
    }
  }, [])

  const handleStartWorkflow = async (caseNumber) => {
    try {
      const response = await fetch('http://localhost:5000/api/workflow/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_number: caseNumber })
      })
      const data = await response.json()
      setActiveWorkflow(data)
      setWorkflows(prev => ({
        ...prev,
        [caseNumber]: {
          caseNumber,
          roomId: data.room_id,
          status: 'running',
          stages: {
            brief: { status: 'pending', output: '' },
            guide: { status: 'pending', output: '' },
            solve: { status: 'pending', output: '' }
          }
        }
      }))

      // Join the WebSocket room
      if (socket) {
        socket.emit('join', { room_id: data.room_id })
      }
    } catch (error) {
      console.error('Failed to start workflow:', error)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <header className="mb-12 text-center">
          <h1 className="text-5xl font-bold bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent mb-2">
            case-wizard
          </h1>
          <p className="text-slate-300 text-lg">
            Three-stage automation for support cases: brief → guide → solve
          </p>
        </header>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column: Case Input */}
          <div className="lg:col-span-1">
            <CaseInput onStart={handleStartWorkflow} />
          </div>

          {/* Right Column: Workflow Status */}
          <div className="lg:col-span-2">
            {activeWorkflow ? (
              <WorkflowDashboard
                workflow={activeWorkflow}
                workflows={workflows}
              />
            ) : (
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center">
                <p className="text-slate-400 text-lg">
                  Enter a case number to get started
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-16 text-center text-slate-500 text-sm">
          <p>case-wizard v1.0 | Backend: http://localhost:5000</p>
        </footer>
      </div>
    </div>
  )
}
