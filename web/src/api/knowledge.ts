import { ApiError, array, integer, record, str, type Client } from './client'

const root = '/knowledge/documents'
export const statusLabels = {
  processing: 'Đang xử lý', ready: 'Đã sẵn sàng', failed: 'Thất bại', deleting: 'Chưa xóa xong',
} as const
type Status = keyof typeof statusLabels

const explanations = new Map<string, string>([
  ['INVALID_FILENAME', 'Tên tệp không hợp lệ. Hãy đổi tên và tải lại.'],
  ['UPLOAD_TOO_LARGE', 'Tệp vượt giới hạn dung lượng của kho tài liệu.'],
  ['UNSUPPORTED_FILE', 'Hãy chọn tài liệu PDF, DOCX, TXT hoặc MD.'],
  ['MIME_MISMATCH', 'Nội dung tệp không khớp với định dạng đã chọn.'],
  ['INVALID_PDF', 'Không đọc được tài liệu PDF. Hãy kiểm tra tệp gốc.'],
  ['INVALID_DOCX', 'Không đọc được tài liệu Word. Hãy kiểm tra tệp gốc.'],
  ['DOCX_MACROS', 'Hãy dùng tài liệu Word không chứa macro.'],
  ['PDF_ENCRYPTED', 'Hãy tải bản PDF không có mật khẩu.'],
  ['PDF_NO_TEXT', 'PDF chưa có văn bản. Hãy nhận dạng chữ trước khi tải lại.'],
  ['EMPTY_DOCUMENT', 'Tài liệu trống hoặc chưa có văn bản đọc được.'],
  ['INVALID_TEXT', 'Hãy lưu văn bản dưới dạng UTF-8 hoặc UTF-16 có BOM.'],
  ['DOCUMENT_TOO_LONG', 'Nội dung tài liệu vượt giới hạn xử lý.'],
  ['UPLOAD_REQUIRED', 'Hãy chọn và tải lại tệp gốc.'],
  ['FILE_INTEGRITY_ERROR', 'Bản lưu của tệp không còn nguyên vẹn. Hãy tải lại tệp gốc.'],
  ['DOCUMENT_NOT_FOUND', 'Tài liệu không còn trong kho.'],
  ['RAG_MODEL_UNAVAILABLE', 'Dịch vụ lập chỉ mục hiện chưa sẵn sàng.'],
  ['DELETE_PENDING', 'Tài liệu đang chờ hoàn tất xóa.'],
])

function documentItem(value: unknown) {
  const row = record(value)
  const status = str(row.indexing_status)
  if (!Object.hasOwn(statusLabels, status)) throw new Error('Kho trả về trạng thái tài liệu chưa được hỗ trợ.')
  const uploaded = new Date(str(row.uploaded_at))
  if (!Number.isFinite(uploaded.getTime())) throw new Error('Ngày tải tài liệu không hợp lệ.')
  const issue = row.error_code || row.error_message
    ? explanations.get(String(row.error_code)) ?? 'Hệ thống chưa xử lý xong tài liệu. Hãy kiểm tra tệp hoặc thử lại sau.'
    : null
  return { id: str(row.document_id), name: str(row.original_filename), type: str(row.file_type).toUpperCase(),
    size: integer(row.file_size), chunks: integer(row.chunk_count), uploaded, status: status as Status, issue,
    canRetry: status === 'failed' && typeof row.stored_relative_path === 'string' && row.stored_relative_path.length > 0 }
}
export type DocumentItem = ReturnType<typeof documentItem>

export async function listDocuments(client: Client, _: string, signal: AbortSignal) {
  return array(await client(root, { signal })).map(documentItem)
}
export async function listBuiltin(client: Client, _: string, signal: AbortSignal) {
  return array(await client('/knowledge/builtin', { signal })).map(record).map(r => ({
    id: str(r.document_id), name: str(r.original_filename),
  }))
}
export async function uploadDocument(client: Client, file: File, signal: AbortSignal) {
  const body = new FormData()
  body.append('file', file)
  return documentItem(await client(root, { body, signal, expectedStatus: 201 }))
}
function path(id: string) { return root + '/' + encodeURIComponent(id) }
export async function retryDocument(client: Client, id: string, signal: AbortSignal) {
  return documentItem(await client(path(id) + '/retry', { method: 'POST', signal }))
}
export function deleteDocument(client: Client, id: string, signal: AbortSignal) {
  return client(path(id), { method: 'DELETE', signal, expectedStatus: 204 })
}
export function operationError(err: unknown, deleting: boolean) {
  if (err instanceof ApiError) {
    if (deleting && err.status === 503) return 'Chưa hoàn tất xóa tệp và dữ liệu vector. Kiểm tra danh sách rồi tiếp tục xóa.'
    if (err.status === 0) return err.message + ' Hãy kiểm tra lại danh sách trước khi thử lại.'
    return explanations.get(err.code ?? '') ?? err.message
  }
  return 'Chưa xác minh được kết quả. Hãy kiểm tra lại danh sách tài liệu.'
}
