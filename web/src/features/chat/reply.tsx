import { BadgeCheck, FileText, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table } from '@/components/ui/table'
import { actionable, type Decision, type Reply } from '@/api/chat'

function Facts({ fields }: { fields: [string, string][] }) {
  return <dl className="chat-facts">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
}
function FinancialResult({ result }: { result: NonNullable<Reply['financial']> }) {
  if (result.kind === 'summary') return <Facts fields={result.fields}/>
  if (result.kind === 'empty') return <p className="subtle">Không có dữ liệu trong kỳ được hỏi.</p>
  return <section className="chat-result"><h3>{result.title}</h3>{result.rows.length
    ? <div className="chat-table"><Table label={result.title} columns={result.headers.map((label, i) => ({ label, render: (row: string[]) => row[i] }))}
        rows={result.rows} rowKey={row => result.rows.indexOf(row)}/></div>
    : <p className="subtle">Không có giao dịch trong kỳ được hỏi.</p>}</section>
}

export type Restriction = { decision: Decision, checked: boolean }
type Props = { response: Reply, locked: boolean, restriction?: Restriction, decide: (thread: string, decision?: Decision) => void }
const agentErrors: Record<string, string> = {
  LLM_NOT_CONFIGURED: 'Dịch vụ AI chưa được cấu hình. Hãy liên hệ người quản trị.',
  LLM_RATE_LIMIT: 'Đã đạt giới hạn lượt hỏi. Hãy thử lại sau.',
  LLM_REQUEST_REJECTED: 'Nhà cung cấp AI đã từ chối yêu cầu xử lý.',
  INVALID_MODEL_OUTPUT: 'Phản hồi của AI sai định dạng. Hãy thử diễn đạt lại yêu cầu.',
}
export function AgentReply({ response: r, locked, restriction, decide }: Props) {
  const failed = r.status === 'ERROR'
  const label = r.phase === 'cancelled' ? 'Đã hủy' : r.phase === 'superseded' ? 'Đã thay thế' :
    r.status === 'NEEDS_CLARIFICATION' ? 'Cần bổ sung' : ''
  const message = failed ? agentErrors[r.errorCode] ??
    'Trợ lý chưa xử lý được yêu cầu này. Bạn có thể kiểm tra lại nội dung và gửi lại.' : r.message
  return <section className="chat-answer" aria-label="Phản hồi của MoneyMind AI">
    <header><span className="ai-mark answer-mark"><Sparkles/></span><strong>MoneyMind AI</strong>{failed ? <Badge tone="danger">Lỗi xử lý</Badge> : label && <Badge tone="warning">{label}</Badge>}</header>
    <p className="chat-text" role={failed ? 'alert' : undefined}>{message}</p>
    {r.financial && <FinancialResult result={r.financial}/>}
    {actionable(r) && <section className="chat-proposal">
      <header><h3>{r.pending?.title ?? 'Bản nháp chưa đầy đủ'}</h3><Badge tone="warning">Chờ xác nhận</Badge></header>
      {r.version != null && r.version > 1n && <p className="subtle">Phiên bản {String(r.version)}</p>}
      {r.pending && <Facts fields={r.pending.fields}/>}
      <div className="chat-actions">
        {r.pending && <><Button disabled={locked || (!!restriction && (!restriction.checked || restriction.decision !== 'CONFIRM'))}
          onClick={() => decide(r.thread, 'CONFIRM')}>Xác nhận</Button>
        <Button variant="outline" disabled={locked || (!!restriction && (!restriction.checked || restriction.decision !== 'CANCEL'))}
          onClick={() => decide(r.thread, 'CANCEL')}>Hủy</Button></>}
        <Button variant="ghost" disabled={locked} onClick={() => decide(r.thread)}>Kiểm tra trạng thái</Button>
      </div>
    </section>}
    {r.receipt && <section className="chat-proposal receipt"><header><BadgeCheck/><h3>Đã lưu thành công</h3><Badge tone="success">Biên nhận #{String(r.receipt.id)}</Badge></header><Facts fields={r.receipt.fields}/></section>}
    {r.sources.length > 0 && <details className="chat-sources"><summary>Nguồn tham khảo ({r.sources.length})</summary>
      <ol>{r.sources.map((s, i) => <li key={i}><FileText aria-hidden="true"/><strong>{s.title}</strong>{s.name !== s.title && ' · ' + s.name}{s.page && ' · Trang ' + s.page}
        {s.evidence && <blockquote>{s.evidence}</blockquote>}{s.url && <a href={s.url} target="_blank" rel="noreferrer">Mở nguồn {i + 1}</a>}</li>)}</ol></details>}
  </section>
}
