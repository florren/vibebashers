import { useEffect, useState } from 'react'

function currentNight() {
  const { circadian, phase } = document.documentElement.dataset
  return circadian === 'true' && phase === 'night'
}

/** Одна интерпретация circadian dataset для глобального и scoped digest. */
export function useNight() {
  const [night, setNight] = useState(currentNight)
  useEffect(() => {
    const observer = new MutationObserver(() => setNight(currentNight()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-circadian', 'data-phase'] })
    return () => observer.disconnect()
  }, [])
  return night
}
