import { useCallback, useEffect, useRef, useState } from 'react'

/** Loads once and on demand. A failed reload never leaves stale data on screen
 *  pretending to be current: the error replaces it. */
export function useApi(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const mounted = useRef(true)
  const run = useCallback(() => {
    setState((previous) => ({ ...previous, loading: true }))
    loader()
      .then((data) => mounted.current && setState({ data, error: null, loading: false }))
      .catch((error) => mounted.current && setState({ data: null, error, loading: false }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    mounted.current = true
    run()
    return () => {
      mounted.current = false
    }
  }, [run])

  return { ...state, reload: run }
}

/** Polls a refresh run until the backend reports it finished. */
export function useRefreshRun(api) {
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  const poll = useCallback(
    async (runId, onDone) => {
      try {
        const current = await api.refreshRun(runId)
        setRun(current)
        if (current.status === 'running') {
          timer.current = setTimeout(() => poll(runId, onDone), 2000)
        } else {
          onDone?.(current)
        }
      } catch (problem) {
        setError(problem)
      }
    },
    [api],
  )

  const start = useCallback(
    async (tickers, onDone) => {
      setError(null)
      try {
        const started = await api.refresh(tickers)
        setRun({ id: started.run_id, status: 'running' })
        poll(started.run_id, onDone)
      } catch (problem) {
        setError(problem)
      }
    },
    [api, poll],
  )

  useEffect(() => stop, [stop])
  return { run, error, start, busy: run?.status === 'running' }
}

export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'system')
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])
  return [theme, setTheme]
}
