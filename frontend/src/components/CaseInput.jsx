import { useState } from 'react'
import { Play, Loader } from 'lucide-react'

export default function CaseInput({ onStart }) {
  const [caseNumber, setCaseNumber] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!caseNumber.trim()) {
      setError('Case number is required')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      await onStart(caseNumber.toUpperCase().trim())
      setCaseNumber('')
    } catch (err) {
      setError(err.message || 'Failed to start workflow')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <h2 className="text-2xl font-bold text-white mb-4">New Case</h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="caseNumber" className="block text-sm font-medium text-slate-300 mb-2">
            Case Number
          </label>
          <input
            id="caseNumber"
            type="text"
            placeholder="T2611845"
            value={caseNumber}
            onChange={(e) => setCaseNumber(e.target.value)}
            disabled={isLoading}
            className="w-full px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed uppercase"
          />
        </div>

        {error && (
          <div className="p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-300 text-sm">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={isLoading || !caseNumber.trim()}
          className="w-full px-4 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-semibold rounded-lg hover:from-blue-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-800 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <Loader className="w-5 h-5 animate-spin" />
              Starting...
            </>
          ) : (
            <>
              <Play className="w-5 h-5" />
              Start Automation
            </>
          )}
        </button>
      </form>

      <div className="mt-6 p-4 bg-slate-700/50 rounded-lg">
        <h3 className="text-sm font-semibold text-slate-300 mb-2">What happens:</h3>
        <ul className="text-sm text-slate-400 space-y-1">
          <li>✓ Gathers case context (CRM, ADO, BC)</li>
          <li>✓ Generates implementation guide</li>
          <li>✓ Auto-implements changes</li>
          <li>✓ Runs verification & tests</li>
          <li>✓ Creates logical commits</li>
        </ul>
      </div>
    </div>
  )
}
