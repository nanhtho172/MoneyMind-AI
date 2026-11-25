import { useState } from 'react'
import { ArrowUpRight, Layers3, Pencil, PieChart, Plus, Wallet } from 'lucide-react'
import { budgetStatus, periodQuery, type BudgetRow } from '@/api/budgets'
import { getCategories } from '@/api/transactions'
import { CategoryLabel } from '@/components/category-label'
import { Engraving } from '@/components/engraving'
import { PageHeader } from '@/components/page-header'
import { PanelState } from '@/components/panel-state'
import { PeriodPicker } from '@/components/period-picker'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { currentPeriod, money } from '@/lib/period'
import { useAuth } from '@/features/auth/auth'
import { useResource } from '@/features/dashboard/use-resource'
import { BudgetForm } from './budget-form'

const alerts = {
  NORMAL: { label: 'Bình thường', tone: 'success' },
  WARNING: { label: 'Gần hạn mức', tone: 'warning' },
  EXCEEDED: { label: 'Đã chạm hạn mức', tone: 'danger' },
} as const
const percentFormat = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 })
const precisePercent = new Intl.NumberFormat('vi-VN', { maximumSignificantDigits: 17 })

function displayPercent(value: number) {
  const nearThreshold = [80, 100].some(boundary => value !== boundary && Math.round(value * 100) === boundary * 100)
  return (nearThreshold ? precisePercent : percentFormat).format(value)
}

function BudgetOverview({ rows }: { rows: BudgetRow[] }) {
  const cards = [
    { key: 'amount', label: 'Tổng hạn mức', icon: Layers3, style: 'income' },
    { key: 'spent', label: 'Đã chi trong ngân sách', icon: ArrowUpRight, style: 'expense' },
    { key: 'remaining', label: 'Tổng còn lại', icon: Wallet, style: 'net' },
  ] as const
  return <section aria-label="Tổng hợp các danh mục có ngân sách" className="metrics budget-metrics">
    {cards.map(({ key, label, icon: Icon, style }) => {
      const amount = rows.reduce((sum, row) => sum + row[key], 0n)
      return <Card key={key} className={'metric ' + style} data-negative={key === 'remaining' && amount < 0n}>
      {key === 'remaining' && <Engraving/>}
      <div className="metric-heading"><span>{label}</span><span className="metric-icon"><Icon/></span></div>
      <strong>{money(amount)}</strong>
    </Card>})}
  </section>
}

function CategoryBudget({ item, edit, disabled }: { item: BudgetRow, edit: () => void, disabled: boolean }) {
  const { label, tone } = alerts[item.alert]
  return <article className="budget-row" aria-label={item.name} data-alert={item.alert}>
    <header><h3><CategoryLabel name={item.name}/></h3><Badge tone={tone}>{label}</Badge></header>
    <div className="budget-details">
      <div className="budget-usage"><span>Đã dùng <b>{displayPercent(item.percent)}%</b></span>
        <div aria-hidden="true" className="budget-track"><i style={{ width: Math.min(100, Math.max(0, item.percent)) + '%' }}/></div>
      </div>
      <dl>{[['Hạn mức', money(item.amount)], ['Đã chi', money(item.spent)], ['Còn lại', money(item.remaining)]].map(([name, value]) =>
        <div key={name}><dt>{name}</dt><dd className={name === 'Còn lại' && item.remaining < 0n ? 'budget-negative' : ''}>{value}</dd></div>)}</dl>
      <Button variant="outline" disabled={disabled} onClick={edit} aria-label={'Cập nhật hạn mức ' + item.name}><Pencil/>Cập nhật</Button>
    </div>
  </article>
}

export default function Budgets() {
  const client = useAuth().session!.request
  const [period, setPeriod] = useState(currentPeriod)
  const [pickerVersion, resetPicker] = useState(0)
  const [editor, setEditor] = useState<{ row?: BudgetRow } | null>(null)
  const [notice, setNotice] = useState('')
  const status = useResource(client, periodQuery(period), budgetStatus)
  const categories = useResource(client, 'type=EXPENSE', getCategories)
  const options = categories.result.state === 'ready' ? categories.result.data.filter(c => c.type === 'EXPENSE') : []
  return <>
    <PageHeader title="Ngân sách" description="Theo dõi chi tiêu so với hạn mức của từng danh mục.">
      <div className="budget-controls"><PeriodPicker key={pickerVersion} value={period} change={value => { setNotice(''); setPeriod(value) }}/>
        <Button disabled={!options.length} onClick={() => setEditor({})}><Plus/>Đặt hạn mức</Button></div>
    </PageHeader>
    {notice && <p role="status" className="tx-notice">{notice}</p>}
    {categories.result.state === 'error' && <PanelState retry={categories.retry}>Không tải được danh mục chi tiêu. {categories.result.message}</PanelState>}
    {categories.result.state === 'loading' && <PanelState>Đang tải danh mục chi tiêu…</PanelState>}
    {categories.result.state === 'ready' && !options.length && <PanelState>Chưa có danh mục chi tiêu để đặt hạn mức.</PanelState>}
    {status.result.state === 'loading' && <div role="status" className="budget-loading"><span className="sr-only">Đang tải ngân sách…</span><i/><i/><i/></div>}
    {status.result.state === 'error' && <PanelState retry={status.retry}>{status.result.message}</PanelState>}
    {status.result.state === 'ready' && <>
      <BudgetOverview rows={status.result.data}/>
      <section className="budget-list"><CardHeader icon={<PieChart/>}>Ngân sách theo danh mục</CardHeader>
        {status.result.data.length === 0 && <PanelState>Kỳ này chưa có ngân sách.</PanelState>}
        <div className="budget-grid">{status.result.data.map(item => <CategoryBudget key={item.id} item={item} disabled={!options.some(c => c.id === item.category_id)} edit={() => setEditor({ row: item })}/>)}</div>
      </section>
    </>}
    {editor && <BudgetForm client={client} categories={options} period={period} row={editor.row} close={() => setEditor(null)}
      saved={(target, text) => {
        setNotice(text)
        setPeriod({ year: target.year, month: target.month })
        resetPicker(n => n + 1)
        status.retry()
      }}/>}
  </>
}
