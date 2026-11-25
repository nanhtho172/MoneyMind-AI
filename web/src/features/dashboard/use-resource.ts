import { useEffect, useState } from 'react'
import type { Client } from '@/api/client'

type Result<T> = { state: 'loading' } | { state: 'error', message: string } | { state: 'ready', data: T }
export function useResource<T>(client: Client, key: string, load: (client: Client, key: string, signal: AbortSignal) => Promise<T>) {
  const [revision, refresh] = useState(0)
  const [entry, setEntry] = useState<{ key: string, revision: number, client: Client, result: Result<T> }>()
  useEffect(() => {
    const controller = new AbortController()
    function publish(result: Result<T>) {
      if (!controller.signal.aborted) setEntry({ key, revision, client, result })
    }
    load(client, key, controller.signal).then(data => publish({ state: 'ready', data }))
      .catch(error => publish({ state: 'error', message: error instanceof Error ? error.message : 'Không tải được dữ liệu.' }))
    return () => controller.abort()
  }, [client, key, revision, load])
  const result: Result<T> = entry?.key === key && entry.client === client && entry.revision === revision ? entry.result : { state: 'loading' }
  return { result, retry: () => refresh(n => n + 1) }
}
