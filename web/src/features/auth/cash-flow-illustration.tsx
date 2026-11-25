// Paired columns on an isometric ledger. All dimensions describe illustration geometry.
const months = [
  { label: 'T1', income: 60, expense: 38 },
  { label: 'T2', income: 86, expense: 51 },
  { label: 'T3', income: 102, expense: 66 },
  { label: 'T4', income: 137, expense: 74 },
]

function Column({ x, y, height, light }: { x: number, y: number, height: number, light?: boolean }) {
  return <g transform={`translate(${x} ${y})`} className={light ? 'ledger-column light' : 'ledger-column'}>
    <path className="ledger-front" d={`M0 0 l30 9 v-${height} l-30 -9 Z`}/>
    <path className="ledger-side" d={`M30 9 l16 -12 v-${height} l-16 12 Z`}/>
    <path className="ledger-top" d={`M0 -${height} l16 -12 30 9 -16 12 Z`}/>
  </g>
}

export function CashFlowIllustration() {
  return <figure className="login-ledger" aria-label="Minh họa so sánh thu nhập và chi tiêu trong bốn tháng">
    <figcaption><span className="ledger-key">Thu nhập</span><span className="ledger-key expense-key">Chi tiêu</span><span className="ledger-caption">Minh họa</span></figcaption>
    <svg viewBox="0 -16 520 244" aria-hidden="true" focusable="false">
      <g className="ledger-grid" fill="none">
        {Array.from({ length: 24 }, (_, i) =>
          <path key={i} d={`M${24 + i*16} ${119 + i*3.2} l96 -72`}/>)}
        {Array.from({ length: 7 }, (_, i) =>
          <path key={i} d={`M${24 + i*16} ${119 - i*12} l368 73.6`}/>)}
      </g>
      {months.map(({ label, income, expense }, i) => {
        const x = 69 + i * 91
        const y = 113 + i * 18.2
        return <g key={label}>
          <Column x={x + 29} y={y - 22} height={income}/>
          <Column x={x} y={y} height={expense} light/>
          <text x={x - 8} y={y + 35} className="ledger-month">{label}</text>
        </g>
      })}
    </svg>
  </figure>
}
