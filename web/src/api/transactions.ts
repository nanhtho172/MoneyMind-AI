import { array, integer, record, str, type Client } from './client'

export type Kind = 'INCOME' | 'EXPENSE'
export type Category = { id: bigint, name: string, type: Kind }
export type Payload = { category_id: bigint, type: Kind, amount: bigint, transaction_date: string, note: string | null }
export type Write = Payload & { idempotency_key: string }
export const maxInt64 = 9223372036854775807n

function kind(value: unknown): Kind {
  if (value === 'INCOME' || value === 'EXPENSE') return value
  throw new Error('Loại giao dịch không hợp lệ.')
}

export function civilDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false
  const [year, month, day] = value.split('-').map(Number)
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  return day >= 1 && day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
}

function positiveInt64(value: unknown) {
  const n = integer(value)
  if (n <= 0n || n > maxInt64) throw new Error('Số nguyên trong giao dịch không hợp lệ.')
  return n
}

export async function getCategories(client: Client, query: string, signal: AbortSignal): Promise<Category[]> {
  return array(await client('/categories' + (query ? '?' + query : ''), { signal })).map(value => {
    const row = record(value)
    return { id: positiveInt64(row.id), name: str(row.name), type: kind(row.type) }
  })
}

function transaction(value: unknown) {
  const row = record(value)
  const date = str(row.transaction_date)
  const created = str(row.created_at)
  if (!civilDate(date) || !Number.isFinite(Date.parse(created))) throw new Error('Ngày trong giao dịch không hợp lệ.')
  return { id: positiveInt64(row.id), type: kind(row.type), category_id: positiveInt64(row.category_id),
    transaction_date: date, amount: positiveInt64(row.amount), note: row.note === null ? null : str(row.note),
    created_at: created, idempotency_key: row.idempotency_key === null ? null : str(row.idempotency_key) }
}

export async function getTransactions(client: Client, query: string, signal: AbortSignal) {
  const page = record(await client('/transactions?' + query, { signal }))
  return { items: array(page.items).map(transaction), page: positiveInt64(page.page),
    pageSize: positiveInt64(page.page_size), total: integer(page.total) }
}

export async function saveTransaction(client: Client, body: Write) {
  const saved = transaction(await client('/transactions', { body }))
  if (saved.idempotency_key !== body.idempotency_key || saved.amount !== body.amount ||
      saved.category_id !== body.category_id || saved.type !== body.type ||
      saved.transaction_date !== body.transaction_date || saved.note !== body.note) {
    throw new Error('Biên nhận chưa khớp với giao dịch đã gửi.')
  }
  return saved
}
