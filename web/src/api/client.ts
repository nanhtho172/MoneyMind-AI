import { decodeJson, encodeJson } from './json'

export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly code?: string) { super(message) }
}
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Dữ liệu trả về sai cấu trúc.')
  return value as Record<string, unknown>
}
export function str(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Trường văn bản không hợp lệ.')
  return value
}
export function integer(value: unknown): bigint {
  if (typeof value !== 'bigint') throw new Error('Số nguyên trong phản hồi không hợp lệ.')
  return value
}
export function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Danh sách trả về sai cấu trúc.')
  return value
}
export function createClient(token: string | null, lifetime: AbortSignal, onUnauthorized?: () => void) {
  return async function request(path: string, options: { method?: 'POST' | 'PUT' | 'DELETE', body?: unknown, signal?: AbortSignal, expectedStatus?: number } = {}) {
    const signal = options.signal ? AbortSignal.any([lifetime, options.signal]) : lifetime
    const headers = new Headers({ Accept: 'application/json' })
    if (token) headers.set('Authorization', 'Bearer ' + token)
    const multipart = options.body instanceof FormData
    if (options.body !== undefined && !multipart) headers.set('Content-Type', 'application/json')
    const deadline = AbortSignal.timeout(75000)
    let response: Response
    let text: string
    try {
      response = await fetch('/api' + path, { headers, signal: AbortSignal.any([signal, deadline]), cache: 'no-store',
        method: options.method ?? (options.body === undefined ? 'GET' : 'POST'),
        body: multipart ? options.body as FormData : options.body === undefined ? undefined : encodeJson(options.body) })
      if (response.status === 401 && !signal.aborted) onUnauthorized?.()
      text = await response.text()
    } catch (error) {
      if (signal.aborted) throw error
      throw new ApiError(0, deadline.aborted ? 'Máy chủ phản hồi quá chậm.' : 'Không kết nối được máy chủ.')
    }
    signal.throwIfAborted()
    if (!response.ok) {
      const messages: Record<number, string> = { 401: 'Thông tin đăng nhập không hợp lệ.', 403: 'Bạn chưa có quyền truy cập.', 422: 'Dữ liệu gửi lên không hợp lệ.', 429: 'Quá nhiều yêu cầu. Hãy thử lại sau.', 503: 'Máy chủ đang bận.' }
      let code: string | undefined
      try {
        const detail = record(record(decodeJson(text)).detail)
        if (typeof detail.code === 'string') code = detail.code
      } catch { /* Other endpoints may return a plain message or an empty body. */ }
      throw new ApiError(response.status, messages[response.status] || 'Yêu cầu thất bại (HTTP ' + response.status + ').', code)
    }
    if (options.expectedStatus && response.status !== options.expectedStatus) throw new Error('Phản hồi chưa xác nhận kết quả thao tác.')
    return response.status === 204 ? null : decodeJson(text)
  }
}
export type Client = ReturnType<typeof createClient>
