import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpFromLine, CircleCheck, Clock3, TriangleAlert, FileType2, FileCode2, File, FileText, Files, FolderOpen, MessageSquare, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { deleteDocument, listDocuments, operationError, retryDocument, statusLabels, uploadDocument, type DocumentItem } from '@/api/knowledge'
import { PageHeader } from '@/components/page-header'
import { PanelState } from '@/components/panel-state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Table } from '@/components/ui/table'
import { useAuth } from '@/features/auth/auth'
import { useResource } from '@/features/dashboard/use-resource'

const tone = { processing: 'neutral', ready: 'success', failed: 'danger', deleting: 'warning' } as const
const date = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeZone: 'Asia/Ho_Chi_Minh' })
function size(bytes: bigint) {
  if (bytes < 1024n) return bytes + ' B'
  const mb = bytes >= 1048576n
  return (Number(bytes) / (mb ? 1048576 : 1024)).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + (mb ? ' MiB' : ' KiB')
}

function FileGlyph({ format }: { format: string }) {
  const Icon = ({ PDF: FileType2, DOCX: FileText, TXT: File, MD: FileCode2 })[format] ?? File
  return <span className="category-glyph" data-tone={format === 'PDF' ? 'coral' : format === 'DOCX' ? 'blue' : 'mint'}><Icon aria-hidden="true"/></span>
}

type Action = { kind: 'upload', file: File } | { kind: 'retry' | 'delete', item: DocumentItem }
type Notice = { text: string, error?: boolean }

export default function Knowledge() {
  const client = useAuth().session!.request
  const documents = useResource(client, 'uploads', listDocuments)
  const rows = documents.result.state === 'ready' ? documents.result.data : undefined
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState<Action | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [target, setTarget] = useState<DocumentItem | null>(null)
  const active = useRef<AbortController | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => () => active.current?.abort(), [])
  useEffect(() => { if (target) dialog.current?.showModal() }, [target])
  useEffect(() => {
    if (!busy && rows?.some(item => item.status === 'processing')) {
      const timer = window.setTimeout(documents.retry, 5000)
      return () => window.clearTimeout(timer)
    }
  }, [rows, busy, documents.retry])

  function select(files: FileList | null) {
    if (active.current || !files?.length) return
    setNotice(null)
    if (files.length !== 1 || !/\.(pdf|docx|txt|md)$/i.test(files[0].name)) {
      setFile(null)
      setNotice({ error: true, text: 'Hãy chọn một tệp PDF, DOCX, TXT hoặc MD cho mỗi lần tải.' })
    } else setFile(files[0])
  }
  async function act(action: Action) {
    if (active.current) return
    const scope = new AbortController()
    active.current = scope
    setBusy(action)
    setNotice(null)
    try {
      if (action.kind === 'delete') {
        await deleteDocument(client, action.item.id, scope.signal)
        setNotice({ text: 'Đã xóa ' + action.item.name + '.' })
      } else {
        const result = action.kind === 'upload' ? await uploadDocument(client, action.file, scope.signal)
          : await retryDocument(client, action.item.id, scope.signal)
        if (action.kind === 'upload') setFile(null)
        const status = result.status === 'ready' ? 'Đã sẵn sàng trong Chat AI.' : result.status === 'processing'
          ? 'Đã tiếp nhận để lập chỉ mục.' : result.issue ?? statusLabels[result.status]
        setNotice({ text: result.name + ' · ' + status, error: result.status === 'failed' || result.status === 'deleting' })
      }
    } catch (err) {
      if (!scope.signal.aborted) setNotice({ text: operationError(err, action.kind === 'delete'), error: true })
    } finally {
      if (!scope.signal.aborted) { active.current = null; setBusy(null); documents.retry() }
    }
  }
  const readyCount = rows?.filter(item => item.status === 'ready').length
  return <>
    <PageHeader title="Kho tài liệu" description="Quản lý nguồn kiến thức được sử dụng bởi trợ lý tài chính AI.">
      {!!readyCount && <Button asChild variant="outline"><Link to="/chat"><MessageSquare/>Mở Chat AI</Link></Button>}
    </PageHeader>
    <div className="kb-top">
      <Card className="kb-upload">
        <CardHeader icon={<ArrowUpFromLine/>}>Thêm tài liệu mới</CardHeader>
        <div className="kb-upload-body">
          <div className="kb-drop" data-dragging={dragging} onDragOver={e => { e.preventDefault(); setDragging(!busy) }}
            onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false) }}
            onDrop={e => { e.preventDefault(); setDragging(false); select(e.dataTransfer.files) }}>
            <span className="kb-file-icon"><ArrowUpFromLine aria-hidden="true"/></span>
            <div className="kb-file-copy"><strong>{file ? file.name : 'Kéo thả tài liệu vào đây'}</strong>
              <small>{file ? size(BigInt(file.size)) : 'PDF, DOCX, TXT hoặc MD · Mỗi lần một tệp'}</small></div>
            <div hidden><Input type="file" ref={picker} accept=".pdf,.docx,.txt,.md" aria-label="Tệp tải lên"
              onChange={e => { select(e.currentTarget.files); e.currentTarget.value = '' }}/></div>
            <Button variant="outline" disabled={!!busy} onClick={() => picker.current?.click()}>{file ? 'Chọn tệp khác' : 'Chọn tài liệu'}</Button>
          </div>
          <div className="kb-upload-actions"><p>Kho dùng chung cho người đã đăng nhập. Tệp tải lên được tự động lập chỉ mục.</p>
            <Button disabled={!file || !!busy} onClick={() => { if (file) void act({ kind: 'upload', file }) }}><ArrowUpFromLine/>{busy?.kind === 'upload' ? 'Đang tải và xử lý…' : 'Tải lên'}</Button></div>
        </div>
      </Card>
      <Card className="kb-overview"><CardHeader icon={<Files/>}>Tổng quan tài liệu tải lên</CardHeader>
        {rows ? <dl><div><Files/><dt>Tổng tài liệu</dt><dd>{rows.length}</dd></div>
          <div><CircleCheck/><dt>Đã sẵn sàng</dt><dd>{readyCount}</dd></div>
          <div><Clock3/><dt>Đang xử lý</dt><dd>{rows.filter(item => item.status === 'processing').length}</dd></div>
          <div><TriangleAlert/><dt>Cần chú ý</dt><dd>{rows.filter(item => item.status === 'failed' || item.status === 'deleting').length}</dd></div></dl>
          : <PanelState>{documents.result.state === 'error' ? 'Chưa có số liệu tổng quan.' : 'Đang tải số liệu…'}</PanelState>}
      </Card>
    </div>
    {notice && <p className="kb-notice" data-error={!!notice.error} role={notice.error ? 'alert' : 'status'}>{notice.text}</p>}
    <Card className="kb-library"><div className="kb-heading"><CardHeader icon={<FolderOpen/>}>Tài liệu đã tải lên</CardHeader>
      <Button variant="ghost" disabled={!!busy || documents.result.state === 'loading'} onClick={documents.retry}><RefreshCw/>Làm mới</Button></div>
      {documents.result.state === 'loading' && <PanelState>Đang tải danh sách tài liệu…</PanelState>}
      {documents.result.state === 'error' && <PanelState retry={documents.retry}>{documents.result.message}</PanelState>}
      {rows && (rows.length === 0 ? <PanelState>Chưa có tài liệu tải lên.</PanelState> :
        <Table label="Tài liệu đã tải lên" rows={rows} rowKey={r => r.id} columns={[
          { label: 'Tài liệu', render: r => <div className="kb-file"><FileGlyph format={r.type}/><div className="kb-file-copy"><strong>{r.name}</strong><small>{r.type} · {size(r.size)}</small></div></div> },
          { label: 'Ngày tải lên', render: r => <time dateTime={r.uploaded.toISOString()}>{date.format(r.uploaded)}</time> },
          { label: 'Lập chỉ mục', render: r => <div className="kb-status"><Badge tone={tone[r.status]}>{statusLabels[r.status]}</Badge>
            {r.issue && <small>{r.issue}</small>}{r.status === 'failed' && !r.canRetry && <small>Hãy tải lại tệp gốc.</small>}</div> },
          { label: 'Số đoạn', align: 'end', render: r => String(r.chunks) },
          { label: 'Thao tác', align: 'end', render: r => <div className="kb-row-actions">
            {r.canRetry && <Button variant="outline" disabled={!!busy} aria-label={'Thử lại ' + r.name} onClick={() => void act({ kind: 'retry', item: r })}>
              <RotateCcw/>{busy?.kind === 'retry' && busy.item.id === r.id ? 'Đang xử lý…' : 'Thử lại'}</Button>}
            <Button variant="ghost" size="icon" disabled={!!busy} aria-label={'Xóa ' + r.name} title={'Xóa ' + r.name}
              onClick={() => setTarget(r)}><Trash2/></Button></div> },
        ]}/>)}
      {busy?.kind === 'delete' && <PanelState>Đang xóa tài liệu…</PanelState>}
    </Card>
    <Dialog label="Xóa tài liệu" ref={dialog} className="kb-dialog" onClose={() => setTarget(null)}>
      <h2>Xóa tài liệu khỏi kho chung?</h2><p>Tệp <strong>{target?.name}</strong> và dữ liệu vector tương ứng sẽ được xóa. Trợ lý AI sẽ ngừng sử dụng tài liệu này.</p>
      <div className="kb-row-actions"><Button autoFocus variant="outline" onClick={() => dialog.current?.close()}>Giữ lại</Button>
        <Button onClick={() => { if (target) void act({ kind: 'delete', item: target }); dialog.current?.close() }}>Xác nhận xóa</Button></div>
    </Dialog>
  </>
}
