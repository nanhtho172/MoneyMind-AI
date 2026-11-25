export type Period = { year: number, month: number }
export function currentPeriod(): Period {
  const parts = new Intl.DateTimeFormat('en', { year: 'numeric', month: 'numeric', timeZone: 'Asia/Ho_Chi_Minh' }).formatToParts(new Date())
  return { year: Number(parts.find(p => p.type === 'year')!.value), month: Number(parts.find(p => p.type === 'month')!.value) }
}
export function dateQuery({ year, month }: Period) {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const last = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
  const prefix = String(year).padStart(4, '0') + '-' + String(month).padStart(2, '0') + '-'
  return new URLSearchParams({ start_date: prefix + '01', end_date: prefix + last }).toString()
}
const formatter = new Intl.NumberFormat('vi-VN')
export const money = (amount: bigint) => formatter.format(amount) + ' ₫'
