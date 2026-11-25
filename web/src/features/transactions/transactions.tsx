import { useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Plus, RefreshCw } from 'lucide-react'
import { getCategories, getTransactions, type Kind } from '@/api/transactions'
import { CategoryLabel } from '@/components/category-label'
import { PageHeader } from '@/components/page-header'
import { PeriodPicker } from '@/components/period-picker'
import { PanelState } from '@/components/panel-state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table } from '@/components/ui/table'
import { currentPeriod, dateQuery, money } from '@/lib/period'
import { useAuth } from '@/features/auth/auth'
import { useResource } from '@/features/dashboard/use-resource'
import { EntryForm } from './entry-form'

const filters = [
  { value: '', label: 'Tất cả' }, { value: 'INCOME', label: 'Thu nhập' }, { value: 'EXPENSE', label: 'Chi tiêu' },
] as const

export default function Transactions() {
  const client = useAuth().session!.request
  const [period, setPeriod] = useState(currentPeriod)
  const [type, setType] = useState<Kind | ''>('')
  const [page, setPage] = useState(1)
  const [notice, setNotice] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const query = new URLSearchParams(dateQuery(period))
  query.set('page', String(page))
  query.set('page_size', '20')
  if (type) query.set('type', type)
  const listing = useResource(client, query.toString(), getTransactions)
  const categoryList = useResource(client, '', getCategories)
  const categories = categoryList.result.state === 'ready' ? categoryList.result.data : undefined
  const names = useMemo(() => new Map(categories?.map(item => [item.id, item.name])), [categories])
  const data = listing.result.state === 'ready' ? listing.result.data : undefined
  return <>
    <PageHeader title="Giao dịch" description="Theo dõi và ghi lại các khoản thu chi theo tháng.">
      <Button disabled={!categories?.length} onClick={() => { setNotice(''); dialog.current?.showModal() }}><Plus/>Thêm giao dịch</Button>
    </PageHeader>
    {notice && <p className="tx-notice" role="status">{notice}</p>}
    <Card className="transaction-ledger">
      <header className="ledger-title"><h2>Sổ giao dịch</h2>{data && <span>{String(data.total)} giao dịch</span>}</header>
      <div className="tx-toolbar">
        <div role="group" aria-label="Loại giao dịch" className="tx-filters">
          {filters.map(filter => <Button key={filter.label} variant="ghost" aria-pressed={type === filter.value}
            onClick={() => { setType(filter.value); setPage(1) }}>{filter.label}</Button>)}
        </div>
        <PeriodPicker value={period} change={next => { setPeriod(next); setPage(1) }}/>
      </div>
      {categoryList.result.state === 'error' && <PanelState retry={categoryList.retry}>Không tải được danh mục. {categoryList.result.message}</PanelState>}
      {categories?.length === 0 && <PanelState>Chưa có danh mục để thêm giao dịch.</PanelState>}
      {categoryList.result.state === 'loading' && <PanelState>Đang tải danh mục…</PanelState>}
      {listing.result.state === 'loading' && <PanelState>Đang tải giao dịch…</PanelState>}
      {listing.result.state === 'error' && <PanelState retry={listing.retry}>{listing.result.message}</PanelState>}
      {data && (data.items.length ? <Table label="Danh sách giao dịch" rows={data.items} rowKey={row => row.id} columns={[
        { label: 'Ngày', render: row => row.transaction_date.split('-').reverse().join('/') },
        { label: 'Danh mục', render: row => <CategoryLabel name={names.get(row.category_id) ?? String(row.category_id)}/> },
        { label: 'Loại', render: row => <Badge tone={row.type === 'INCOME' ? 'success' : 'expense'}>{row.type === 'INCOME' ? 'Thu nhập' : 'Chi tiêu'}</Badge> },
        { label: 'Ghi chú', render: row => row.note ?? '—' },
        { label: 'Số tiền', align: 'end', render: row => <span className={row.type === 'INCOME' ? 'positive' : undefined}>{row.type === 'INCOME' ? '+' : '−'}{money(row.amount)}</span> },
      ]}/> : <PanelState>Không có giao dịch trong kỳ đã chọn.</PanelState>)}
      {data && <footer className="tx-pagination"><span>Trang {data.page.toString()} · {data.total.toString()} giao dịch</span>
        <div><Button variant="ghost" size="icon" aria-label="Làm mới danh sách" onClick={listing.retry}><RefreshCw/></Button>
          <Button variant="outline" size="icon" aria-label="Trang trước" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft/></Button>
          <Button variant="outline" size="icon" aria-label="Trang sau" disabled={data.page * data.pageSize >= data.total || page >= 1000000} onClick={() => setPage(page + 1)}><ChevronRight/></Button></div>
      </footer>}
    </Card>
    <EntryForm dialog={dialog} client={client} categories={categories ?? []} onSaved={message => {
      setNotice(message)
      listing.retry()
    }}/>
  </>
}
