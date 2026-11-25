import { useEffect, useRef, useState } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { ApiError, type Client } from '@/api/client'
import { getCategories } from '@/api/transactions'
import { actionable, chatError, createChat, listChats, loadHistory, removeChat, sendChat, threadState,
  type Conversation, type Decision, type History, type Reply } from '@/api/chat'
import type { Restriction } from './reply'

const empty: History = { turns: [], before: null, pinned: null }
type Memory = { drafts: Map<string, string>, decisions: Map<string, Restriction>, notices: Map<string, string> }
const sessions = new WeakMap<Client, Memory>()
function sessionMemory(client: Client) {
  let memory = sessions.get(client)
  if (!memory) {
    memory = { drafts: new Map(), decisions: new Map(), notices: new Map() }
    sessions.set(client, memory)
  }
  return memory
}
export function useConversation(client: Client, id: string, navigate: NavigateFunction) {
  const memory = sessionMemory(client)
  const [items, setItems] = useState<Conversation[]>([])
  const [history, setHistory] = useState<History>(empty)
  const [ready, setReady] = useState(false)
  const [job, setJob] = useState('Đang mở hội thoại…')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState(memory.notices.get(id) ?? '')
  const [draft, setText] = useState(memory.drafts.get(id) ?? '')
  const [sending, setSending] = useState('')
  const alive = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const names = useRef(new Map<bigint, string>())
  const firstLoaded = useRef<string | undefined>(undefined)
  function edit(text: string) {
    if (text) memory.drafts.set(id, text)
    else memory.drafts.delete(id)
    setText(text)
  }
  function open(target: string, replace = false) {
    navigate(target ? '/chat/' + encodeURIComponent(target) : '/chat', { replace })
  }
  async function sync(signal: AbortSignal) {
    setReady(false)
    const catalog = await listChats(client, signal)
    setItems(catalog)
    if (!id && catalog.length) {
      if (window.location.pathname === '/chat' || window.location.pathname === '/chat/') open(catalog[0].id, true)
      return
    }
    if (id && !catalog.some(c => c.id === id)) {
      setError('Hội thoại này không còn khả dụng. Hãy chọn hội thoại khác hoặc tạo mới.')
      setHistory(empty)
      return
    }
    const page = id ? await loadHistory(client, id, names.current, signal) : empty
    // Keep older, explicitly loaded turns visible when a send or decision refreshes the log.
    const anchor = firstLoaded.current
    while (anchor && page.before && !page.turns.some(turn => turn.response.thread === anchor)) {
      const older = await loadHistory(client, id, names.current, signal, page.before)
      page.turns = [...older.turns, ...page.turns]
      page.before = older.before
    }
    setHistory(page)
    setReady(true)
    return page
  }
  useEffect(() => {
    const scope = new AbortController()
    memory.notices.delete(id)
    alive.current = scope
    const signal = scope.signal
    async function initialize() {
      try {
        const categories = await getCategories(client, '', signal).catch(() => [])
        signal.throwIfAborted()
        names.current = new Map(categories.map(c => [c.id, c.name]))
        const page = await sync(signal)
        if (page?.turns.length) setNotice('Đã mở lại hội thoại.')
      } catch (err) { if (!signal.aborted) setError(chatError(err)) }
      finally { if (!signal.aborted) setJob('') }
    }
    void initialize()
    return () => scope.abort()
    // The workspace is keyed by the authenticated session and conversation route.
  }, [client, id])

  async function run(label: string, task: (signal: AbortSignal) => Promise<void>) {
    const signal = alive.current?.signal
    if (busy.current || job || !signal || signal.aborted) return
    busy.current = true
    setJob(label)
    setError('')
    setNotice('')
    try { await task(signal) }
    catch (err) { if (!signal.aborted) setError(chatError(err)) }
    finally {
      if (!signal.aborted) { setJob(''); setSending('') }
      busy.current = false
    }
  }
  const reload = () => run('Đang tải lại hội thoại…', async signal => { await sync(signal) })
  const create = () => run('Đang tạo hội thoại…', async signal => {
    try { open(await createChat(client, signal)) }
    catch (err) { if (!signal.aborted) await sync(signal); throw err }
  })
  const erase = (target: string) => run('Đang xóa hội thoại…', async signal => {
    try { await removeChat(client, target, signal) }
    catch (err) {
      if (signal.aborted) throw err
      const catalog = await listChats(client, signal)
      setItems(catalog)
      if (catalog.some(item => item.id === target)) throw err
    }
    memory.drafts.delete(target)
    if (target === id) open(items.find(item => item.id !== target)?.id ?? '', true)
    else await sync(signal)
  })
  const send = () => run('Trợ lý đang xử lý…', async signal => {
    const message = draft.trim()
    if (!ready || !message || message.length > 1500) return
    let target = id
    if (!target) {
      try { target = await createChat(client, signal) }
      catch (err) { if (!signal.aborted) await sync(signal); throw err }
      memory.drafts.set(target, draft)
      memory.drafts.delete('')
    }
    setSending(message)
    try {
      const response = await sendChat(client, target, message, names.current, signal)
      setSending('')
      if (response.status !== 'ERROR') { memory.drafts.delete(target); setText('') }
      if (!id) { open(target, true); return }
      setHistory(old => ({ ...old, turns: [...old.turns, { message, response }] }))
    } catch (err) {
      if (signal.aborted) throw err
      let problem = chatError(err)
      if (!(err instanceof ApiError) || err.status === 0 || err.status >= 500) {
        problem = 'Chưa nhận đủ phản hồi. Hãy đối chiếu lịch sử trước khi gửi lại.'
      }
      if (!id) { memory.notices.set(target, problem); open(target, true); return }
      const page = await sync(signal)
      const known = new Set(history.turns.map(t => t.response.thread))
      const recovered = page?.turns.filter(t => !known.has(t.response.thread) && t.message === message)
      if (recovered?.length === 1 && recovered[0].response.status !== 'ERROR') {
        edit('')
        setNotice('Đã tìm thấy lượt trả lời trong lịch sử.')
        return
      }
      setError(problem)
      return
    }
    await sync(signal)
  })
  function replaceReply(response: Reply) {
    setHistory(old => {
      const update = (turn: History['turns'][number]) => turn.response.thread === response.thread ? { ...turn, response } : turn
      return { ...old, turns: old.turns.map(update), pinned: old.pinned && update(old.pinned) }
    })
  }
  const decide = (thread: string, decision?: Decision) => run(decision === 'CONFIRM' ? 'Đang xác nhận…' :
    decision === 'CANCEL' ? 'Đang hủy bản nháp…' : 'Đang kiểm tra trạng thái…', async signal => {
    const prior = memory.decisions.get(thread)
    if (decision && (!ready || (prior && (!prior.checked || prior.decision !== decision)))) return
    if (decision) memory.decisions.set(thread, { decision, checked: false })
    let response: Reply
    let warning = ''
    try { response = await threadState(client, thread, names.current, signal, decision) }
    catch (err) {
      if (signal.aborted) throw err
      if (!decision) {
        if (err instanceof ApiError && err.status === 404) await sync(signal)
        throw err
      }
      warning = chatError(err)
      try { response = await threadState(client, thread, names.current, signal) }
      catch (readError) {
        if (!signal.aborted) await sync(signal)
        throw readError
      }
    }
    replaceReply(response)
    const restriction = memory.decisions.get(thread)
    if (actionable(response) && restriction) restriction.checked = true
    else memory.decisions.delete(thread)
    if (warning && actionable(response)) setError(warning + ' Đã đối chiếu trạng thái bản nháp.')
    await sync(signal)
  })
  const older = (beforeInsert: () => void) => run('Đang tải lượt cũ…', async signal => {
    if (!history.before) return
    const page = await loadHistory(client, id, names.current, signal, history.before)
    beforeInsert()
    firstLoaded.current = page.turns[0]?.response.thread
    setHistory(old => ({ turns: [...page.turns, ...old.turns], before: page.before, pinned: old.pinned }))
  })
  return { items, history, ready, job, error, notice, draft, sending, edit, open, reload, create, erase, send, decide, older, restrictions: memory.decisions }
}
