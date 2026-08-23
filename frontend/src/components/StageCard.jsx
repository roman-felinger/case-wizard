import { CheckCircle, Loader, AlertCircle } from 'lucide-react'

export default function StageCard({ stage, status, output, isActive }) {
  const getStatusColor = () => {
    switch (status) {
      case 'complete': return 'text-green-400'
      case 'running': return 'text-blue-400'
      case 'error': return 'text-red-400'
      default: return 'text-slate-400'
    }
  }

  const getStatusIcon = () => {
    switch (status) {
      case 'complete': return <CheckCircle className={`w-5 h-5 ${getStatusColor()}`} />
      case 'running': return <Loader className={`w-5 h-5 ${getStatusColor()} animate-spin`} />
      case 'error': return <AlertCircle className={`w-5 h-5 ${getStatusColor()}`} />
      default: return <div className="w-5 h-5 rounded-full border-2 border-slate-600" />
    }
  }

  return (
    <div className={`p-4 rounded-lg border transition-all ${
      isActive
        ? 'bg-slate-700 border-blue-500 shadow-lg shadow-blue-500/20'
        : 'bg-slate-800 border-slate-700'
    }`}>
      <div className="flex items-center gap-3 mb-2">
        {getStatusIcon()}
        <h3 className="font-semibold text-white capitalize">{stage}</h3>
        <span className={`text-xs font-medium px-2 py-1 rounded-full ${
          status === 'complete' ? 'bg-green-900/50 text-green-300' :
          status === 'running' ? 'bg-blue-900/50 text-blue-300' :
          status === 'error' ? 'bg-red-900/50 text-red-300' :
          'bg-slate-700 text-slate-400'
        }`}>
          {status}
        </span>
      </div>
      {output && <p className="text-xs text-slate-400 line-clamp-2">{output}</p>}
    </div>
  )
}
