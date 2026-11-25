import { array, integer, record, str, type Client } from './client'
import { maxInt64 } from './transactions'
import type { Period } from '@/lib/period'

export type BudgetWrite = Period & { category_id: bigint, amount: bigint }
export const periodQuery = ({ year, month }: Period) => new URLSearchParams({ year: String(year), month: String(month) }).toString()

function budgetView(value: unknown) {
  const row = record(value)
  const id = integer(row.id), category_id = integer(row.category_id), amount = integer(row.amount)
  const year = Number(integer(row.year)), month = Number(integer(row.month))
  if (id < 1n || category_id < 1n || amount < 1n || amount > maxInt64 || year < 1 || year > 9999 || month < 1 || month > 12) {
    throw new Error('Hạn mức trả về không hợp lệ.')
  }
  return { id, year, month, category_id, amount }
}

export async function budgetStatus(client: Client, query: string, signal?: AbortSignal) {
  return array(await client('/budgets/status?' + query, { signal })).map(value => {
    const row = record(value)
    const view = budgetView(row)
    if (periodQuery(view) !== query) throw new Error('Máy chủ trả ngân sách khác kỳ đang xem.')
    const alert = row.alert
    const raw = row.usage_percent
    const percent = typeof raw === 'bigint' ? Number(raw) : raw
    if ((alert !== 'NORMAL' && alert !== 'WARNING' && alert !== 'EXCEEDED') || typeof percent !== 'number' || !Number.isFinite(percent)) {
      throw new Error('Trạng thái ngân sách không hợp lệ.')
    }
    return { ...view, name: str(row.category_name), spent: integer(row.spent), remaining: integer(row.remaining),
      percent, alert: alert as 'NORMAL' | 'WARNING' | 'EXCEEDED' }
  })
}
export type BudgetRow = Awaited<ReturnType<typeof budgetStatus>>[number]

export async function setBudget(client: Client, body: BudgetWrite) {
  const result = budgetView(await client('/budgets', { method: 'PUT', body }))
  if (result.year !== body.year || result.month !== body.month || result.category_id !== body.category_id || result.amount !== body.amount) {
    throw new Error('Biên nhận chưa khớp với hạn mức đã gửi.')
  }
}
