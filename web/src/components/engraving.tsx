/** Stationery motif. Pure linework, independent of financial data. */
export function Engraving() {
  return <svg className="engraving" viewBox="0 0 320 200" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
    <g fill="none" stroke="currentColor" strokeWidth="1">
      {Array.from({ length: 34 }, (_, i) => <ellipse key={i} cx="175" cy="98" rx={116 - i * 1.5} ry={70 - i}
        transform={`rotate(${i * 3 - 35} 175 98)`}/>)}
    </g>
  </svg>
}
