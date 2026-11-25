import { ApiError, array, integer, record, str, type Client } from './client'
import { money } from '@/lib/period'

const root = '/chat/conversations'
export type Decision = 'CONFIRM' | 'CANCEL'
const optional = (value: unknown) => value == null ? '' : str(value)
function choice<T extends string>(value: unknown, options: readonly T[]): T {
  const match = options.find(option => option === value)
  if (!match) throw new Error('Phản hồi chưa hợp lệ.')
  return match
}
const typeName = (value: unknown) => choice(value, ['INCOME', 'EXPENSE'] as const) === 'INCOME' ? 'Thu nhập' : 'Chi tiêu'
const date = (value: unknown) => str(value).split('-').reverse().join('/')
const vnd = (value: unknown) => money(integer(value))
type Fields = [string, string][]
function details(value: unknown, transaction: boolean, category?: string): Fields {
  const p = record(value)
  const fields: Fields = [['Số tiền', vnd(p.amount)]]
  if (category) fields.push(['Danh mục', category])
  if (transaction) {
    fields.push(['Loại', typeName(p.type)], ['Ngày', date(p.transaction_date)])
    if (p.note) fields.push(['Ghi chú', str(p.note)])
  } else fields.push(['Kỳ ngân sách', integer(p.month) + '/' + integer(p.year)])
  return fields
}
function pending(value: unknown) {
  const row = record(value)
  const kind = choice(row.kind, ['CREATE_TRANSACTION', 'SET_BUDGET'] as const)
  const fields = details(row.payload, kind === 'CREATE_TRANSACTION', str(row.category))
  return { title: kind === 'CREATE_TRANSACTION' ? 'Xác nhận giao dịch' : 'Xác nhận hạn mức', fields }
}
type Financial = { kind: 'summary', fields: Fields } | { kind: 'table', title: string, headers: string[], rows: string[][] } | { kind: 'empty' }
function financial(value: unknown, names: Map<bigint, string>): Financial {
  if (Array.isArray(value)) {
    if (!value.length) return { kind: 'empty' }
    const rows = value.map(record)
    if ('spent' in rows[0]) {
      const alerts = { NORMAL: 'Bình thường', WARNING: 'Gần hạn mức', EXCEEDED: 'Đã chạm hạn mức' }
      return { kind: 'table', title: 'Ngân sách theo danh mục', headers: ['Danh mục', 'Kỳ', 'Hạn mức', 'Đã chi', 'Còn lại', 'Đã dùng', 'Trạng thái'],
        rows: rows.map(r => [str(r.category_name), integer(r.month) + '/' + integer(r.year), vnd(r.amount), vnd(r.spent),
          vnd(r.remaining), new Intl.NumberFormat('vi-VN', { maximumSignificantDigits: 17 }).format(Number(r.usage_percent)) + '%',
          alerts[choice(r.alert, ['NORMAL', 'WARNING', 'EXCEEDED'] as const)]]) }
    }
    return { kind: 'table', title: 'Chi tiêu theo danh mục', headers: ['Danh mục', 'Đã chi'], rows: rows.map(r => [str(r.category_name), vnd(r.total_expense)]) }
  }
  const r = record(value)
  if ('items' in r) return { kind: 'table', title: 'Giao dịch · Trang ' + integer(r.page) + ' · ' + integer(r.total) + ' giao dịch',
    headers: ['Ngày', 'Danh mục', 'Loại', 'Số tiền', 'Ghi chú'], rows: array(r.items).map(record).map(item =>
      [date(item.transaction_date), names.get(integer(item.category_id)) ?? 'Danh mục #' + integer(item.category_id),
        typeName(item.type), vnd(item.amount), optional(item.note) || '—']) }
  return { kind: 'summary', fields: [['Thu nhập', vnd(r.total_income)], ['Chi tiêu', vnd(r.total_expense)], ['Dòng tiền ròng', vnd(r.net_cash_flow)]] }
}
function source(value: unknown) {
  const s = record(value)
  const url = optional(s.source_url)
  return { title: optional(s.original_filename) || optional(s.document_title) || str(s.title), name: optional(s.source_name) || str(s.source),
    url: /^https?:\/\//i.test(url) ? url : '', page: s.page_number == null ? '' : String(integer(s.page_number)), evidence: optional(s.evidence) }
}
function reply(value: unknown, names: Map<bigint, string>) {
  const r = record(value)
  const receipt = r.status === 'COMPLETED' && r.structured_data != null ? record(r.structured_data) : null
  return { thread: str(r.thread_id), status: choice(r.status, ['COMPLETED', 'NEEDS_CLARIFICATION', 'PENDING_CONFIRMATION', 'ERROR'] as const),
    message: str(r.message), errorCode: optional(r.error_code), phase: optional(r.pending_state), version: r.draft_version == null ? null : integer(r.draft_version),
    pending: r.pending_action == null ? null : pending(r.pending_action),
    receipt: receipt && { id: integer(receipt.id), fields: details(receipt, 'transaction_date' in receipt,
      typeof receipt.category_id === 'bigint' ? names.get(receipt.category_id) : undefined) },
    financial: r.financial_data == null ? null : financial(r.financial_data, names), sources: array(r.sources ?? []).map(source) }
}
export type Reply = ReturnType<typeof reply>
export type Turn = { message: string, response: Reply }
export type Conversation = { id: string, title: string, updated: string }
export type History = { turns: Turn[], before: bigint | null, pinned: Turn | null }
export const actionable = (r: Reply) => r.status === 'PENDING_CONFIRMATION' && (!r.phase || r.phase === 'ready_for_confirmation')
export async function listChats(client: Client, signal: AbortSignal): Promise<Conversation[]> {
  return array(await client(root, { signal })).map(record).map(r => ({ id: str(r.conversation_id), title: str(r.title), updated: optional(r.updated_at) }))
}
export async function createChat(client: Client, signal: AbortSignal) {
  return str(record(await client(root, { method: 'POST', signal })).conversation_id)
}
const path = (id: string) => root + '/' + encodeURIComponent(id)
export const removeChat = (client: Client, id: string, signal: AbortSignal) => client(path(id), { method: 'DELETE', body: { confirmed: true }, signal })
export async function loadHistory(client: Client, id: string, names: Map<bigint, string>, signal: AbortSignal, before?: bigint): Promise<History> {
  const r = record(await client(path(id) + (before ? '?before=' + before : ''), { signal }))
  if (r.conversation_id !== id) throw new Error('Hội thoại không khớp.')
  function turn(value: unknown): Turn {
    const t = record(value)
    return { message: str(t.message), response: reply(t.response, names) }
  }
  return { turns: array(r.turns).map(turn), before: r.next_before == null ? null : integer(r.next_before), pinned: r.earlier_pending ? turn(r.earlier_pending) : null }
}
export async function sendChat(client: Client, id: string, message: string, names: Map<bigint, string>, signal: AbortSignal) {
  return reply(await client('/chat', { body: { conversation_id: id, message }, signal }), names)
}
export async function threadState(client: Client, thread: string, names: Map<bigint, string>, signal: AbortSignal, decision?: Decision) {
  const prefix = '/chat/' + encodeURIComponent(thread)
  const result = reply(await (decision ? client(prefix + '/confirm', { body: { decision }, signal }) : client(prefix + '/state', { signal })), names)
  if (result.thread !== thread) throw new Error('Lượt trả về không khớp.')
  return result
}
export function chatError(err: unknown) {
  if (!(err instanceof ApiError)) return 'Chưa đọc được kết quả. Hãy kiểm tra lại hội thoại.'
  if (err.status === 404) return 'Hội thoại hoặc bản nháp này không còn khả dụng.'
  if (err.status === 409) return 'Bản nháp đã thay đổi. Hãy kiểm tra trạng thái mới nhất.'
  if (err.status >= 500) return 'Dịch vụ chat đang gián đoạn. Hãy kiểm tra lại sau.'
  return err.message
}
