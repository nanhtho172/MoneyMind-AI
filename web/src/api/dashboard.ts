import { array, integer, record, str, type Client } from './client'

export async function summary(client: Client, query: string, signal: AbortSignal) {
  const row = record(await client('/reports/summary?' + query, { signal }))
  return { income: integer(row.total_income), expense: integer(row.total_expense), net: integer(row.net_cash_flow) }
}
export async function spending(client: Client, query: string, signal: AbortSignal) {
  return array(await client('/reports/by-category?' + query, { signal })).map(item => {
    const row = record(item)
    return { id: integer(row.category_id), name: str(row.category_name), amount: integer(row.total_expense) }
  })
}
export async function recent(client: Client, query: string, signal: AbortSignal) {
  const page = record(await client('/transactions?' + query + '&page=1&page_size=5', { signal }))
  return array(page.items).map(item => {
    const row = record(item)
    if (row.type !== 'INCOME' && row.type !== 'EXPENSE') throw new Error('Loại giao dịch không hợp lệ.')
    return { id: integer(row.id), category: integer(row.category_id), income: row.type === 'INCOME',
      amount: integer(row.amount), date: str(row.transaction_date).split('-').reverse().join('/'), note: row.note === null ? '' : str(row.note) }
  })
}
export async function categories(client: Client, _query: string, signal: AbortSignal) {
  return new Map(array(await client('/categories', { signal })).map(item => {
    const row = record(item)
    return [integer(row.id), str(row.name)]
  }))
}
