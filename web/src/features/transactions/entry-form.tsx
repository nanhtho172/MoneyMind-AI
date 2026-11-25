import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react'
import { ApiError, type Client } from '@/api/client'
import { encodeJson } from '@/api/json'
import { civilDate, maxInt64, saveTransaction, type Category, type Write, type Payload } from '@/api/transactions'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input, Select, Textarea } from '@/components/ui/input'
import { money } from '@/lib/period'

type Draft = { category: string, amount: string, date: string, note: string }
type Errors = Partial<Record<keyof Draft, string>>
type Attempt = { signature: string, body: Write, conflict?: boolean }
// Outstanding writes follow the authenticated client across route changes; logout drops access.
const outstanding = new WeakMap<Client, Attempt>()

function initialDraft(client: Client): Draft {
  const body = outstanding.get(client)?.body
  if (body) return { category: String(body.category_id), amount: String(body.amount), date: body.transaction_date, note: body.note ?? '' }
  const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
  return { category: '', amount: '', date, note: '' }
}

type Props = {
  dialog: RefObject<HTMLDialogElement | null>, client: Client, categories: Category[], onSaved: (notice: string) => void
}

export function EntryForm({ dialog, client, categories, onSaved }: Props) {
  const [draft, setDraft] = useState(() => initialDraft(client))
  const [errors, setErrors] = useState<Errors>({})
  const [message, setMessage] = useState(() => outstanding.has(client) ? 'Hãy đối chiếu giao dịch trước khi thử lại.' : '')
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  useEffect(() => {
    const viewport = window.visualViewport
    function fitKeyboard() {
      const element = dialog.current
      if (!viewport || !element) return
      if (viewport.scale === 1 && viewport.height < window.innerHeight - 80) {
        element.style.setProperty('--tx-visible-height', viewport.height + 'px')
        element.style.setProperty('--tx-visible-top', (viewport.offsetTop + 8) + 'px')
      } else {
        element.style.removeProperty('--tx-visible-height')
        element.style.removeProperty('--tx-visible-top')
      }
    }
    viewport?.addEventListener('resize', fitKeyboard)
    viewport?.addEventListener('scroll', fitKeyboard)
    return () => {
      viewport?.removeEventListener('resize', fitKeyboard)
      viewport?.removeEventListener('scroll', fitKeyboard)
    }
  }, [dialog])

  function field(name: keyof Draft) {
    return { id: 'tx-' + name, name, value: draft[name], 'aria-invalid': !!errors[name],
      'aria-describedby': errors[name] ? 'tx-error-' + name : undefined,
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
        const value = event.currentTarget.value
        setDraft(previous => ({ ...previous, [name]: value }))
        setErrors(previous => ({ ...previous, [name]: undefined }))
      } }
  }
  function fieldError(name: keyof Draft) {
    return errors[name] && <p className="tx-field-error" id={'tx-error-' + name}>{errors[name]}</p>
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sending.current) return
    const invalid: Errors = {}
    const category = categories.find(item => String(item.id) === draft.category)
    if (!category) invalid.category = 'Hãy chọn một danh mục.'
    const digits = draft.amount.trim()
    const amount = /^\d{1,19}$/.test(digits) ? BigInt(digits) : 0n
    if (amount <= 0n || amount > maxInt64) invalid.amount = 'Nhập số nguyên dương, tối đa 9.223.372.036.854.775.807 ₫.'
    if (!civilDate(draft.date)) invalid.date = 'Hãy chọn ngày giao dịch hợp lệ.'
    if (Array.from(draft.note).length > 500) invalid.note = 'Ghi chú tối đa 500 ký tự.'
    setErrors(invalid)
    const first = Object.keys(invalid)[0]
    if (first || !category) {
      event.currentTarget.querySelector<HTMLElement>('[name="' + first + '"]')?.focus()
      return
    }
    const payload: Payload = { category_id: category.id, type: category.type, amount,
      transaction_date: draft.date, note: draft.note.trim() || null }
    const signature = encodeJson(payload)
    let attempt = outstanding.get(client)
    if (attempt?.signature === signature && attempt.conflict) {
      setMessage('Khóa giao dịch bị xung đột. Hãy kiểm tra lại danh sách trước khi nhập giao dịch mới.')
      return
    }
    if (!attempt || attempt.signature !== signature) {
      attempt = { signature, body: { ...payload, idempotency_key: 'ui:' + crypto.randomUUID() } }
      outstanding.set(client, attempt)
    }
    sending.current = true
    setBusy(true)
    setMessage('')
    try {
      const saved = await saveTransaction(client, attempt.body)
      if (outstanding.get(client) === attempt) outstanding.delete(client)
      setDraft(initialDraft(client))
      dialog.current?.close()
      onSaved('Đã lưu giao dịch #' + saved.id + ' · ' + money(saved.amount) + '.')
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        attempt.conflict = true
        setMessage('Khóa giao dịch bị xung đột. Hãy kiểm tra lại danh sách trước khi nhập giao dịch mới.')
      } else if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        setMessage(error.message)
      } else {
        setMessage('Chưa xác định được kết quả lưu. Hãy kiểm tra danh sách hoặc thử lại cùng nội dung để tránh ghi trùng.')
      }
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  return <Dialog ref={dialog} label="Thêm giao dịch" className="tx-dialog"
    onCancel={e => { if (sending.current) e.preventDefault() }}
    onClick={e => { if (sending.current && e.target === e.currentTarget) e.preventDefault() }}
    onClose={() => {
      if (!outstanding.has(client)) { setDraft(initialDraft(client)); setMessage(''); setErrors({}) }
    }}>
    <h2>Thêm giao dịch</h2>
    <form noValidate onSubmit={submit} aria-busy={busy}>
      <fieldset disabled={busy} className="tx-fields">
        <div><label htmlFor="tx-category">Danh mục</label>
          <Select {...field('category')} required autoFocus><option value="">Chọn danh mục</option>
            {categories.map(item => <option key={item.id} value={String(item.id)}>{item.name} · {item.type === 'INCOME' ? 'Thu nhập' : 'Chi tiêu'}</option>)}
          </Select>{fieldError('category')}</div>
        <div><label htmlFor="tx-amount">Số tiền (VNĐ)</label>
          <Input {...field('amount')} required inputMode="numeric" placeholder="35000"/>{fieldError('amount')}</div>
        <div><label htmlFor="tx-date">Ngày giao dịch</label>
          <Input {...field('date')} required type="date" min="0001-01-01" max="9999-12-31"/>{fieldError('date')}</div>
        <div><label htmlFor="tx-note">Ghi chú <span>(tùy chọn)</span></label>
          <Textarea {...field('note')} rows={2} maxLength={500}/>{fieldError('note')}</div>
      </fieldset>
      {message && <p role="alert" className="tx-feedback">{message}</p>}
      <div className="tx-actions"><Button variant="outline" type="button" disabled={busy} onClick={() => dialog.current?.close()}>Hủy</Button>
        <Button disabled={busy} type="submit">{busy ? 'Đang lưu…' : 'Lưu giao dịch'}</Button></div>
    </form>
  </Dialog>
}
