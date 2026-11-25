import type { ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from './ui/button'

export function PanelState({ children, retry }: { children: ReactNode, retry?: () => void }) {
  return <div className="panel-state" role={retry ? 'alert' : 'status'}>
    {children}
    {retry && <Button variant="ghost" onClick={retry}><RefreshCw/>Thử lại</Button>}
  </div>
}
