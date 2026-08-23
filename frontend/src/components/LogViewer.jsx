export default function LogViewer({ content }) {
  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-3 overflow-x-auto">
      <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap break-words">
        {content || 'No output yet...'}
      </pre>
    </div>
  )
}
