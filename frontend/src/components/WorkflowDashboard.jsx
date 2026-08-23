import { useEffect, useState } from 'react'
import { CheckCircle, Loader, AlertCircle, ChevronRight } from 'lucide-react'
import StageCard from './StageCard'
import LogViewer from './LogViewer'

export default function WorkflowDashboard({ workflow, workflows }) {
  const [currentWorkflow, setCurrentWorkflow] = useState(null)
  const [expandedLogs, setExpandedLogs] = useState(null)

  useEffect(() => {
    if (workflow && workflows[workflow.case_number]) {
      setCurrentWorkflow(workflows[workflow.case_number])
    }
  }, [workflow, workflows])

  if (!currentWorkflow) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center">
        <Loader className="w-8 h-8 animate-spin text-blue-400 mx-auto mb-4" />
        <p className="text-slate-300">Loading workflow...</p>
      </div>
    )
  }

  const stages = [
    {
      id: 'brief',
      name: 'Gather Brief',
      description: 'Context from CRM, ADO, BC',
      icon: '📋'
    },
    {
      id: 'guide',
      name: 'Generate Guide',
      description: 'Implementation walkthrough',
      icon: '📖'
    },
    {
      id: 'solve',
      name: 'Auto-Implement',
      description: 'Apply changes & verify',
      icon: '⚙️'
    }
  ]

  const getStageStatus = (stageId) => {
    const stage = currentWorkflow.stages?.[stageId]
    if (!stage) return 'pending'
    return stage.status
  }

  const isStageActive = (stageId) => {
    return currentWorkflow.stage === stageId
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'complete':
        return <CheckCircle className="w-6 h-6 text-green-400" />
      case 'running':
        return <Loader className="w-6 h-6 text-blue-400 animate-spin" />
      case 'error':
        return <AlertCircle className="w-6 h-6 text-red-400" />
      default:
        return <div className="w-6 h-6 rounded-full border-2 border-slate-600" />
    }
  }

  return (
    <div className="space-y-6">
      {/* Pipeline Visualization */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
        <h2 className="text-2xl font-bold text-white mb-6">
          Case: <span className="text-blue-400">{workflow.case_number}</span>
        </h2>

        {/* Stages Pipeline */}
        <div className="space-y-4">
          {stages.map((stage, index) => (
            <div key={stage.id}>
              <div className="flex items-center gap-4">
                <div className={`flex-shrink-0 ${isStageActive(stage.id) ? 'scale-110' : ''} transition-transform`}>
                  {getStatusIcon(getStageStatus(stage.id))}
                </div>

                <div className="flex-grow">
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <h3 className="text-lg font-semibold text-white">{stage.name}</h3>
                      <p className="text-sm text-slate-400">{stage.description}</p>
                    </div>
                    <div className="text-sm font-medium px-3 py-1 rounded-full bg-slate-700 text-slate-300 capitalize">
                      {getStageStatus(stage.id)}
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-500 ${
                        getStageStatus(stage.id) === 'complete'
                          ? 'w-full bg-green-500'
                          : getStageStatus(stage.id) === 'running'
                          ? 'w-1/2 bg-blue-500'
                          : 'w-0 bg-slate-600'
                      }`}
                    />
                  </div>
                </div>
              </div>

              {/* Expandable Logs */}
              {currentWorkflow.stages?.[stage.id]?.output && (
                <div className="mt-3 ml-10">
                  <button
                    onClick={() => setExpandedLogs(expandedLogs === stage.id ? null : stage.id)}
                    className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1 mb-2"
                  >
                    <ChevronRight className={`w-4 h-4 transition-transform ${expandedLogs === stage.id ? 'rotate-90' : ''}`} />
                    {expandedLogs === stage.id ? 'Hide' : 'Show'} output
                  </button>

                  {expandedLogs === stage.id && (
                    <LogViewer content={currentWorkflow.stages[stage.id].output} />
                  )}
                </div>
              )}

              {/* Arrow Between Stages */}
              {index < stages.length - 1 && (
                <div className="flex justify-center my-2">
                  <ChevronRight className="w-6 h-6 text-slate-600 rotate-90" />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Overall Status */}
        {currentWorkflow.status === 'complete' && (
          <div className="mt-6 p-4 bg-green-900/20 border border-green-800 rounded-lg">
            <p className="text-green-300 font-medium flex items-center gap-2">
              <CheckCircle className="w-5 h-5" />
              ✓ Workflow completed successfully!
            </p>
            <p className="text-sm text-green-400 mt-1">
              Check the verification checklist at: case-solves/case-{workflow.case_number}/VERIFICATION_CHECKLIST.md
            </p>
          </div>
        )}

        {currentWorkflow.error && (
          <div className="mt-6 p-4 bg-red-900/20 border border-red-800 rounded-lg">
            <p className="text-red-300 font-medium flex items-center gap-2">
              <AlertCircle className="w-5 h-5" />
              Error: {currentWorkflow.error}
            </p>
          </div>
        )}
      </div>

      {/* Results Preview */}
      {currentWorkflow.status === 'complete' && (
        <ResultsPanel caseNumber={workflow.case_number} />
      )}
    </div>
  )
}

function ResultsPanel({ caseNumber }) {
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`http://localhost:5000/api/results/${caseNumber}`)
      .then(r => r.json())
      .then(setResults)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [caseNumber])

  if (loading) return null

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <h3 className="text-xl font-bold text-white mb-4">Results</h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {results?.brief_content && (
          <div className="p-4 bg-slate-700/50 rounded-lg">
            <p className="text-sm font-medium text-slate-300 mb-2">📋 Brief</p>
            <p className="text-xs text-slate-400 line-clamp-3">{results.brief_content.slice(0, 150)}...</p>
          </div>
        )}
        {results?.guide_content && (
          <div className="p-4 bg-slate-700/50 rounded-lg">
            <p className="text-sm font-medium text-slate-300 mb-2">📖 Guide</p>
            <p className="text-xs text-slate-400 line-clamp-3">{results.guide_content.slice(0, 150)}...</p>
          </div>
        )}
        <div className="p-4 bg-slate-700/50 rounded-lg">
          <p className="text-sm font-medium text-slate-300 mb-2">✓ Verification</p>
          <p className="text-xs text-slate-400">Checklist ready in case-solves/</p>
        </div>
      </div>
    </div>
  )
}
