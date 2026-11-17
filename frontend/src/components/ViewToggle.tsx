import { useState } from 'react'

export type DayView = 'timeline' | 'storylines'

const KEY = 'cyoa.dayView'

/** Remembered per device (just a display preference). */
export function useDayView(): [DayView, (v: DayView) => void] {
  const [view, setView] = useState<DayView>(() => {
    try {
      return localStorage.getItem(KEY) === 'storylines' ? 'storylines' : 'timeline'
    } catch {
      return 'timeline'
    }
  })
  const set = (v: DayView) => {
    setView(v)
    try {
      localStorage.setItem(KEY, v)
    } catch {
      /* storage unavailable - fine */
    }
  }
  return [view, set]
}

export default function ViewToggle({
  view,
  onChange,
  firstLabel = 'Timeline',
  secondLabel = 'Storylines',
}: {
  view: DayView
  onChange: (v: DayView) => void
  firstLabel?: string
  secondLabel?: string
}) {
  return (
    <div className="seg view-toggle" role="tablist">
      <button role="tab" aria-selected={view === 'timeline'} className={view === 'timeline' ? 'on' : ''} onClick={() => onChange('timeline')}>
        {firstLabel}
      </button>
      <button role="tab" aria-selected={view === 'storylines'} className={view === 'storylines' ? 'on' : ''} onClick={() => onChange('storylines')}>
        {secondLabel}
      </button>
    </div>
  )
}
