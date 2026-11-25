import type { Key, ReactNode } from 'react'

type Column<T> = {
  label: string
  align?: 'end'
  render: (row: T) => ReactNode
}

type TableProps<T> = {
  label: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => Key
}

export function Table<T>({ label, columns, rows, rowKey }: TableProps<T>) {
  return <table className="data-table" aria-label={label}>
    <thead><tr>{columns.map(column =>
      <th key={column.label} scope="col" data-align={column.align}>{column.label}</th>
    )}</tr></thead>
    <tbody>{rows.map(row => <tr key={rowKey(row)}>
      {columns.map(column => <td key={column.label} data-label={column.label} data-align={column.align}>
        {column.render(row)}
      </td>)}
    </tr>)}</tbody>
  </table>
}
