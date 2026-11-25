import { useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, ArrowLeftRight, ChartPie, List, ArrowRight, Scale } from 'lucide-react'
import { Pie, PieChart, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { Link } from 'react-router-dom'
import * as api from '@/api/dashboard'
import { useAuth } from '@/features/auth/auth'
import { currentPeriod, dateQuery, money } from '@/lib/period'
import { useResource } from './use-resource'

import { Engraving } from '@/components/engraving'
import { CategoryLabel } from '@/components/category-label'
import { PeriodPicker } from '@/components/period-picker'
import { PanelState } from '@/components/panel-state'
import { PageHeader } from '@/components/page-header'
import { Card, CardHeader } from '@/components/ui/card'
import { Table } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'

function Spending({ rows }: { rows: Awaited<ReturnType<typeof api.spending>> }) {
  if (!rows.length) return <PanelState>Kỳ này chưa có khoản chi.</PanelState>
  const total = rows.reduce((sum, row) => sum + row.amount, 0n)
  const palette = ['primary', 'lime', 'gold', 'info', 'coral', 'chart-2']
  const slices = rows.map((row, i) => ({ ...row,
    share: total ? Number(row.amount * 1000000n / total) : 0,
    color: 'var(--color-' + palette[i % palette.length] + ')' }))
  return <div className="spending-breakdown">
    <div className="spending-ring" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart><Pie data={slices} dataKey="share" nameKey="name" innerRadius="72%" outerRadius="96%"
          startAngle={90} endAngle={-270} stroke="var(--color-surface)" strokeWidth={2} isAnimationActive={false}>
          {slices.map(row => <Cell key={row.id} fill={row.color}/>)}
        </Pie><Tooltip content={({ active, payload }) => {
          const row = active ? payload?.[0]?.payload as typeof slices[number] | undefined : undefined
          return row ? <div className="chart-tip">{row.name}<b>{money(row.amount)}</b></div> : null
        }}/></PieChart>
      </ResponsiveContainer>
      <span className="ring-label"><b>{rows.length}</b>Danh mục</span>
    </div>
    <dl className="spend-values">{slices.map(row => <div key={row.id}>
      <dt><i style={{ backgroundColor: row.color }}/>{row.name}</dt>
      <dd><span className="sr-only">{row.name}: </span>{money(row.amount)}<small>{(row.share / 10000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%</small></dd>
    </div>)}</dl>
  </div>
}

function CashFlowSummary({ income, expense, net }: Awaited<ReturnType<typeof api.summary>>) {
  const rate = income > 0n ? (expense * 1000n + income / 2n) / income : null
  const percent = rate === null ? '—' : (rate / 10n).toString() + (rate % 10n ? ',' + rate % 10n : '') + '%'
  return <div className="cash-flow-summary">
    <p>Chi tiêu trên thu nhập</p><strong>{percent}</strong>
    <div className="ratio-track" aria-hidden="true"><i style={{ width: (rate === null ? 0 : Number(rate > 1000n ? 1000n : rate) / 10) + '%' }}/></div>
    <dl className="flow-values"><div><dt>Thu nhập</dt><dd>{money(income)}</dd></div><div><dt>Chi tiêu</dt><dd>{money(expense)}</dd></div></dl>
    <p>{rate === null ? 'Kỳ này chưa có thu nhập để tính tỷ lệ.' : net === 0n ? 'Thu nhập bằng chi tiêu trong kỳ.' :
      (net > 0n ? 'Thu nhập cao hơn chi tiêu ' : 'Chi tiêu cao hơn thu nhập ') + money(net > 0n ? net : -net) + '.'}</p>
  </div>
}
export function Dashboard() {
  const { session } = useAuth()
  const client = session!.request
  const [period, setPeriod] = useState(currentPeriod)
  const query = dateQuery(period)
  const totals = useResource(client, query, api.summary)
  const expenses = useResource(client, query, api.spending)
  const transactions = useResource(client, query, api.recent)
  const names = useResource(client, '', api.categories)
  const metrics = [
    { key: 'income', label: 'Thu nhập', Icon: ArrowDownLeft },
    { key: 'expense', label: 'Chi tiêu', Icon: ArrowUpRight },
    { key: 'net', label: 'Dòng tiền ròng', Icon: ArrowLeftRight },
  ] as const
  return <><PageHeader title="Tổng quan tài chính" description={`Thu chi cá nhân trong tháng ${period.month} năm ${period.year}.`}><PeriodPicker value={period} change={setPeriod}/></PageHeader>
    <section aria-label="Chỉ số tài chính" className="metrics">{metrics.map(({key,label,Icon}) => <Card key={key} className={'metric ' + key} data-negative={key === 'net' && totals.result.state === 'ready' && totals.result.data.net < 0n}>
      {key === 'net' && <Engraving/>}
      <div className="metric-heading"><span>{label}</span><span className="metric-icon"><Icon/></span></div>
      {totals.result.state === 'ready' ? <strong>{money(totals.result.data[key])}</strong> : <span className="metric-placeholder">{totals.result.state === 'loading' ? 'Đang tải…' : 'Chưa tải được'}</span>}
    </Card>)}</section>
    {totals.result.state === 'error' && <PanelState retry={totals.retry}>{totals.result.message}</PanelState>}
    <div className="dashboard-analysis"><Card><CardHeader icon={<ChartPie/>}>Chi tiêu theo danh mục</CardHeader>
      {expenses.result.state === 'loading' ? <PanelState>Đang tải dữ liệu…</PanelState> : expenses.result.state === 'error' ? <PanelState retry={expenses.retry}>{expenses.result.message}</PanelState> : <Spending rows={expenses.result.data}/>}
    </Card>
    <Card className="summary-panel"><CardHeader icon={<Scale/>}>Tóm tắt dòng tiền</CardHeader>
      {totals.result.state === 'ready' ? <CashFlowSummary {...totals.result.data}/> :
        <PanelState>{totals.result.state === 'loading' ? 'Đang tải số liệu…' : 'Chưa có số liệu để tổng hợp.'}</PanelState>}
    </Card></div>
    <Card className="recent-panel"><div className="recent-heading"><CardHeader icon={<List/>}>Giao dịch gần đây</CardHeader>
      <Link to="/transactions">Mở sổ giao dịch <ArrowRight size={15}/></Link></div>
      {names.result.state === 'error' && <PanelState retry={names.retry}>{'Chưa tải được tên danh mục. ' + names.result.message}</PanelState>}
      {transactions.result.state === 'loading' ? <PanelState>Đang tải dữ liệu…</PanelState> : transactions.result.state === 'error' ? <PanelState retry={transactions.retry}>{transactions.result.message}</PanelState> :
      !transactions.result.data.length ? <PanelState>Không có giao dịch trong kỳ đã chọn.</PanelState> :
      <Table label="Giao dịch gần đây" rows={transactions.result.data} rowKey={row => row.id} columns={[
        { label: 'Ngày', render: row => row.date },
        { label: 'Danh mục', render: row => <CategoryLabel name={names.result.state === 'ready' ? names.result.data.get(row.category) ?? String(row.category) : String(row.category)}/> },
        { label: 'Loại', render: row => <Badge tone={row.income ? 'success' : 'expense'}>{row.income ? 'Khoản thu' : 'Khoản chi'}</Badge> },
        { label: 'Ghi chú', render: row => row.note || '—' },
        { label: 'Số tiền', align: 'end', render: row => <span className={row.income ? 'positive' : undefined}>{(row.income ? '+' : '−') + money(row.amount)}</span> },
      ]}/>}
    </Card></>
}
