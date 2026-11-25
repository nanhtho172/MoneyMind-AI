import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, type Client } from '@/api/client'
import { budgetStatus, periodQuery, setBudget, type BudgetRow, type BudgetWrite } from '@/api/budgets'
import { maxInt64, type Category } from '@/api/transactions'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input, Select } from '@/components/ui/input'
import { money, type Period } from '@/lib/period'

const uncertain = new WeakMap<Client, BudgetWrite>()
type Props = { client: Client, period: Period, row?: BudgetRow, categories: Category[],
  close: () => void, saved: (period: Period, notice: string) => void }

export function BudgetForm({ client, period, row, categories, close, saved }: Props) {
  const initial = uncertain.get(client) ?? row
  const [values, setValues] = useState({ category: initial?.category_id.toString() ?? '', month: String(initial?.month ?? period.month),
    year: String(initial?.year ?? period.year), amount: initial?.amount.toString() ?? '' })
  type Field = keyof typeof values
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const [message, setMessage] = useState(initial && uncertain.has(client) ? 'Cần kiểm tra kết quả lần lưu trước.' : '')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(uncertain.has(client))
  const lock = useRef(false)
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])

  function field(name: Field) {
    return { name, id: 'budget-' + name, value: values[name], 'aria-invalid': !!errors[name],
      'aria-describedby': errors[name] ? 'budget-error-' + name : undefined,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        setValues({ ...values, [name]: e.target.value })
        setErrors({ ...errors, [name]: undefined })
      } }
  }
  function error(name: Field) {
    return errors[name] && <p id={'budget-error-' + name} className="tx-field-error">{errors[name]}</p>
  }
  function complete(body: BudgetWrite, prefix: string) {
    uncertain.delete(client)
    const name = categories.find(c => c.id === body.category_id)?.name ?? String(body.category_id)
    saved(body, prefix + ' ' + money(body.amount) + ' cho ' + name + ' · Tháng ' + body.month + '/' + body.year + '.')
    dialog.current?.close()
  }
  async function reconcile(body: BudgetWrite) {
    setChecking(true)
    setMessage('Chưa xác định được kết quả lưu. Đang đọc lại ngân sách của kỳ đã gửi…')
    try {
      const rows = await budgetStatus(client, periodQuery(body))
      if (rows.some(item => item.category_id === body.category_id && item.amount === body.amount)) {
        complete(body, 'Đã đối chiếu hạn mức')
      } else {
        uncertain.delete(client)
        setChecking(false)
        setMessage('Đã kiểm tra kỳ đã gửi. Hạn mức hiện tại chưa khớp; bạn có thể kiểm tra lại số tiền và bấm Lưu.')
      }
    } catch {
      setMessage('Chưa xác định được kết quả. Hãy kiểm tra trạng thái trước khi lưu lại.')
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (lock.current) return
    const form = event.currentTarget
    const pending = uncertain.get(client)
    const category = categories.find(c => String(c.id) === values.category && c.type === 'EXPENSE')
    const year = Number(values.year), month = Number(values.month)
    const digits = values.amount.trim()
    const amount = /^\d{1,19}$/.test(digits) ? BigInt(digits) : 0n
    const invalid: typeof errors = {}
    if (!category) invalid.category = 'Hãy chọn một danh mục chi tiêu.'
    if (!/^\d{1,2}$/.test(values.month) || month < 1 || month > 12) invalid.month = 'Tháng phải từ 1 đến 12.'
    if (!/^\d{1,4}$/.test(values.year) || year < 1 || year > 9999) invalid.year = 'Năm phải từ 1 đến 9999.'
    if (amount < 1n || amount > maxInt64) invalid.amount = 'Nhập số nguyên dương, tối đa 9.223.372.036.854.775.807 ₫.'
    setErrors(invalid)
    if (!pending && (!category || Object.keys(invalid).length)) {
      form.querySelector<HTMLElement>('[name="' + Object.keys(invalid)[0] + '"]')?.focus()
      return
    }
    lock.current = true
    setBusy(true)
    try {
      if (pending) { await reconcile(pending); return }
      const body = { year, month, category_id: category!.id, amount }
      setMessage('')
      try {
        await setBudget(client, body)
        complete(body, 'Đã lưu hạn mức')
      } catch (err) {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 408) setMessage(err.message)
        else {
          uncertain.set(client, body)
          await reconcile(body)
        }
      }
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  const title = row ? 'Cập nhật hạn mức' : 'Đặt hạn mức'
  return <Dialog ref={dialog} label={title} className="tx-dialog" onClose={close}
    onCancel={e => { if (lock.current) e.preventDefault() }} onClick={e => { if (lock.current && e.target === e.currentTarget) e.preventDefault() }}>
    <h2>{title}</h2><form noValidate onSubmit={submit} aria-busy={busy}>
      <fieldset className="tx-fields" disabled={busy || checking}>
        <div><label htmlFor="budget-category">Danh mục chi tiêu</label>
          <Select {...field('category')} autoFocus required><option value="">Chọn danh mục</option>
            {categories.map(item => <option key={item.id} value={String(item.id)}>{item.name}</option>)}</Select>{error('category')}</div>
        <div className="budget-form-period">
          <div><label htmlFor="budget-month">Tháng</label><Input {...field('month')} required type="number" min="1" max="12"/>{error('month')}</div>
          <div><label htmlFor="budget-year">Năm</label><Input {...field('year')} required type="number" min="1" max="9999"/>{error('year')}</div>
        </div>
        <div><label htmlFor="budget-amount">Hạn mức (VNĐ)</label><Input {...field('amount')} required inputMode="numeric" placeholder="1000000"/>{error('amount')}</div>
      </fieldset>
      {message && <p className="tx-feedback" role="alert">{message}</p>}
      <div className="tx-actions"><Button type="button" variant="outline" disabled={busy} onClick={() => dialog.current?.close()}>Hủy</Button>
        <Button disabled={busy}>{checking ? 'Kiểm tra trạng thái' : busy ? 'Đang lưu…' : 'Lưu hạn mức'}</Button></div>
    </form>
  </Dialog>
}
