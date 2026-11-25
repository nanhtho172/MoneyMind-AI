import { useState } from 'react'
import { CalendarDays } from 'lucide-react'
import type { Period } from '@/lib/period'
import { Input, Select } from './ui/input'

export function PeriodPicker({ value, change }: { value: Period, change: (period: Period) => void }) {
  const [year, setYear] = useState(String(value.year))
  return <div className="period">
    <CalendarDays/><Select aria-label="Tháng" value={value.month} onChange={e => change({ ...value, month: Number(e.target.value) })}>
      {Array.from({ length: 12 }, (_, i) => <option key={i} value={i+1}>Tháng {i+1}</option>)}
    </Select>
    <Input aria-label="Năm" type="number" min="1" max="9999" value={year} onChange={e => {
      setYear(e.target.value)
      const n = Number(e.target.value)
      if (/^\d{1,4}$/.test(e.target.value) && n > 0) change({ ...value, year: n })
    }} onBlur={() => setYear(String(value.year))}/>
  </div>
}
