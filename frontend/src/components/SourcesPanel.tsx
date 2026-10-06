import { useState } from 'react'
import type { Source } from '../types'

const TYPE_LABELS: Record<string, string> = {
  page: 'Page',
  news: 'News',
  service: 'Service',
  category: 'Category',
  office_location: 'Office location',
  discovered: 'Page',
}

export default function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false)

  if (sources.length === 0) return null

  return (
    <div className="mt-3 border-t border-slate-200 pt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-nia-green"
      >
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
          className={`h-4 w-4 transition-transform ${open ? 'rotate-90' : ''}`}
        >
          <path d="M7.5 5l5 5-5 5V5z" />
        </svg>
        {sources.length} {sources.length === 1 ? 'source' : 'sources'}
      </button>

      {open && (
        <ol className="mt-2 space-y-2">
          {sources.map((source) => (
            <li
              key={`${source.index}-${source.url}`}
              className="rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-sm"
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 rounded bg-nia-green px-1.5 py-0.5 text-xs font-semibold text-white">
                  {source.index}
                </span>
                <div className="min-w-0">
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="font-medium text-nia-green underline underline-offset-2"
                  >
                    {source.title}
                  </a>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {TYPE_LABELS[source.content_type] ?? source.content_type}
                    {source.section && source.section !== source.title
                      ? ` · ${source.section}`
                      : ''}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                    {source.snippet}
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
