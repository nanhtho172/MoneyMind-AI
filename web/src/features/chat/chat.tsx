import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowUp, ArrowUpRight, ChartPie, ChartColumn, NotebookPen, Wallet, Sparkles, History as HistoryIcon, Plus, Trash2, X } from 'lucide-react'
import { useAuth } from '@/features/auth/auth'
import { PageHeader } from '@/components/page-header'
import { PanelState } from '@/components/panel-state'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input, Textarea } from '@/components/ui/input'
import type { Conversation } from '@/api/chat'
import { AgentReply } from './reply'
import { useConversation } from './use-conversation'

const questions = [
  { icon: ChartColumn, label: 'Tổng thu chi', prompt: 'Tháng này tôi đã thu và chi bao nhiêu tiền?' },
  { icon: ChartPie, label: 'Chi theo danh mục', prompt: 'Danh mục nào đang chi tiêu nhiều nhất?' },
  { icon: NotebookPen, label: 'Ghi khoản chi', prompt: 'Giúp tôi ghi lại một khoản chi.' },
  { icon: Wallet, label: 'Lập ngân sách', prompt: 'Giúp tôi thiết lập ngân sách cho tháng tới.' },
]
const localTime = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Ho_Chi_Minh' })

export default function Chat() {
  const { conversationId = '' } = useParams()
  return <Workspace key={conversationId} id={conversationId}/>
}
function Workspace({ id }: { id: string }) {
  const chat = useConversation(useAuth().session!.request, id, useNavigate())
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const [search, setSearch] = useState('')
  const drawer = useRef<HTMLDialogElement>(null)
  const confirmDelete = useRef<HTMLDialogElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const page = useRef<HTMLDivElement>(null)
  const atEnd = useRef(true)
  const previousHeight = useRef<number | null>(null)
  const locked = !!chat.job
  useEffect(() => { if (deleting) confirmDelete.current?.showModal() }, [deleting])
  useEffect(() => {
    const viewport = window.visualViewport
    const workspace = page.current?.closest<HTMLElement>('.workspace')
    if (!viewport || !workspace) return
    const resize = () => {
      if (viewport.scale === 1) workspace.style.setProperty('--chat-viewport', viewport.height + 'px')
    }
    resize()
    viewport.addEventListener('resize', resize)
    return () => { viewport.removeEventListener('resize', resize); workspace.style.removeProperty('--chat-viewport') }
  }, [])
  useLayoutEffect(() => {
    const node = scroller.current
    if (!node) return
    if (previousHeight.current !== null) {
      node.scrollTop += node.scrollHeight - previousHeight.current
      previousHeight.current = null
    } else if (atEnd.current) node.scrollTop = node.scrollHeight
  }, [chat.history, chat.sending])
  useLayoutEffect(() => {
    const input = composer.current
    if (input) { input.style.height = 'auto'; input.style.height = input.scrollHeight + 2 + 'px' }
  }, [chat.draft])
  const filtered = chat.items.filter(item => item.title.toLocaleLowerCase('vi').includes(search.trim().toLocaleLowerCase('vi')))
  const historyList = <><header><HistoryIcon aria-hidden="true"/><h2>Lịch sử trò chuyện</h2></header>
    <Button className="history-new" disabled={locked} onClick={() => { drawer.current?.close(); chat.create() }}><Plus/>Cuộc trò chuyện mới</Button>
    {chat.items.length > 1 && <Input aria-label="Tìm trong lịch sử" placeholder="Tìm hội thoại…" value={search} onChange={e => setSearch(e.target.value)}/>}
    {!!chat.items.length && !filtered.length && <p className="subtle">Không tìm thấy hội thoại phù hợp.</p>}
    {!chat.items.length && !locked && <p className="subtle">Chưa có cuộc trò chuyện.</p>}
    <ul>{filtered.map(item => <li key={item.id} data-current={item.id === id}>
      <button className="chat-history-item" aria-current={item.id === id ? 'page' : undefined} disabled={locked}
        onClick={() => { drawer.current?.close(); chat.open(item.id) }}>
        <strong>{item.title}</strong><small>{item.updated ? localTime.format(new Date(item.updated)) : 'Hội thoại cũ'}</small></button>
      <Button variant="ghost" size="icon" disabled={locked} aria-label={'Xóa ' + item.title}
        onClick={() => { drawer.current?.close(); setDeleting(item) }}><Trash2/></Button>
    </li>)}</ul></>
  const pinned = chat.history.pinned
  const reply = (response: Parameters<typeof AgentReply>[0]['response']) =>
    <AgentReply response={response} locked={locked || !chat.ready} restriction={chat.restrictions.get(response.thread)} decide={chat.decide}/>
  return <div ref={page} className="chat-page">
    <Card className="chat-grid">
      <aside className="chat-history">{historyList}</aside>
      <section className="chat-room" aria-label="Cuộc trò chuyện">
        <div className="chat-room-heading"><span className="ai-mark"><Sparkles/></span><PageHeader title="Trợ lý tài chính AI" description="Thu chi, ngân sách và kiến thức tài chính."/>
          <Button variant="outline" className="chat-history-toggle" aria-haspopup="dialog" onClick={() => drawer.current?.showModal()}><HistoryIcon/>Lịch sử</Button>
        </div>
        <div ref={scroller} className="chat-scroll" onScroll={e => {
          const el = e.currentTarget
          atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
        }}>
          {chat.history.before && <Button variant="ghost" disabled={locked} onClick={() => chat.older(() => {
            previousHeight.current = scroller.current?.scrollHeight ?? null
          })}>Tải tin nhắn cũ hơn</Button>}
          {pinned && !chat.history.turns.some(t => t.response.thread === pinned.response.thread) &&
            <section><h3>Bản nháp từ các lượt trước</h3>{reply(pinned.response)}</section>}
          {!chat.history.turns.length && chat.ready && !chat.sending && <div className="chat-empty">
            <span className="ai-mark welcome-mark"><Sparkles/></span><h2>Hôm nay, bạn muốn<br/>xem gì về dòng tiền?</h2>
            <div>{questions.map(({icon: Icon, label, prompt}) => <Button key={label} disabled={locked} variant="outline" onClick={() => { chat.edit(prompt); composer.current?.focus() }}><Icon/>{label}<ArrowUpRight/></Button>)}</div>
          </div>}
          {chat.history.turns.map(t => <article className="chat-turn" key={t.response.thread}>
            <div className="chat-user"><strong>Bạn</strong><p className="chat-text">{t.message}</p></div>
            {reply(t.response)}
          </article>)}
          {chat.sending && <div className="chat-user"><strong>Bạn</strong><p className="chat-text">{chat.sending}</p></div>}
        </div>
        <div className="chat-feedback" data-busy={locked} aria-live="polite">{chat.job || chat.notice}</div>
        {chat.error && <PanelState retry={locked ? undefined : chat.reload}>{chat.error}</PanelState>}
        <form className="chat-composer" onSubmit={e => { e.preventDefault(); void chat.send() }}>
          <label htmlFor="chat-message">Tin nhắn</label>
          <div><Textarea ref={composer} id="chat-message" rows={1} value={chat.draft} maxLength={1500} readOnly={locked || !chat.ready}
            placeholder="Nhập tin nhắn…" onChange={e => chat.edit(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault(); e.currentTarget.form?.requestSubmit()
            } }}/>
          <Button type="submit" disabled={locked || !chat.ready || !chat.draft.trim()}><ArrowUp/>Gửi</Button></div><small>Enter để gửi · Shift + Enter để xuống dòng</small>
        </form>
      </section>
    </Card>
    <Dialog ref={drawer} variant="drawer" label="Lịch sử trò chuyện"><Button variant="ghost" onClick={() => drawer.current?.close()}><X/>Đóng lịch sử</Button>
      <div className="chat-history chat-history-mobile">{historyList}</div></Dialog>
    <Dialog ref={confirmDelete} label="Xóa cuộc trò chuyện" onClose={() => setDeleting(null)}>
      <h2>Xóa cuộc trò chuyện?</h2><p>“{deleting?.title}” và các bản nháp đang chờ sẽ bị xóa.</p>
      <div className="chat-actions"><Button variant="outline" autoFocus onClick={() => confirmDelete.current?.close()}>Giữ lại</Button>
        <Button onClick={() => { if (deleting) void chat.erase(deleting.id); confirmDelete.current?.close() }}>Xác nhận xóa</Button></div>
    </Dialog>
  </div>
}
