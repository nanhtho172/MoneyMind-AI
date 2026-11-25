import streamlit as st

from backend.app.schemas.knowledge import DocumentItem
from frontend.api_client import ApiClient, ApiError

STATUS = {
    "processing": "Đang xử lý", "ready": "Sẵn sàng",
    "failed": "Thất bại", "deleting": "Thất bại",
}


def show_result(item: DocumentItem) -> None:
    if item.indexing_status == "ready":
        st.session_state["knowledge_notice"] = ("success", "Tài liệu đã sẵn sàng trong Chat AI.")
    elif item.indexing_status == "processing":
        st.session_state["knowledge_notice"] = ("info", "Đang xử lý tài liệu.")
    else:
        st.session_state["knowledge_notice"] = ("error", item.error_message or "Xử lý tài liệu thất bại.")
    st.rerun()


def knowledge_library(client: ApiClient) -> None:
    st.title("Kho tài liệu")
    pending = st.session_state.pop("knowledge_notice", None)
    if pending:
        {"success": st.success, "info": st.info, "error": st.error}[pending[0]](pending[1])
    with st.form("knowledge_upload", clear_on_submit=True):
        file = st.file_uploader("Chọn tài liệu", type=["pdf", "docx", "txt", "md"])
        submitted = st.form_submit_button("Tải lên", type="primary")
    if submitted:
        if file is None:
            st.warning("Hãy chọn một tệp.")
        else:
            with st.spinner("Đang xử lý tài liệu…"):
                item = client.knowledge_upload(file.name, file.type, file.getvalue())
            show_result(item)

    items = client.knowledge_documents()
    st.subheader(f"Tài liệu đã tải ({len(items)})")
    if not items:
        st.info("Chưa có tài liệu tải lên.")
    for item in items:
        with st.container(border=True):
            label, status, retry, remove = st.columns([4, 1.5, 1.2, 1])
            label.text(item.original_filename)
            status.text(STATUS[item.indexing_status])
            if item.error_message:
                st.caption(item.error_message)
            if item.indexing_status == "failed" and item.stored_relative_path:
                if retry.button("Thử lại", key=f"retry-{item.document_id}"):
                    with st.spinner("Đang xử lý lại…"):
                        result = client.knowledge_retry(item.document_id)
                    show_result(result)
            if remove.button("Xóa", key=f"delete-{item.document_id}"):
                try:
                    with st.spinner("Đang xóa tài liệu…"):
                        client.knowledge_remove(item.document_id)
                except ApiError as error:
                    if error.status_code != 503:
                        raise
                    st.session_state["knowledge_notice"] = ("error", str(error))
                else:
                    st.session_state["knowledge_notice"] = ("success", "Đã xóa tài liệu.")
                st.rerun()

    builtins = client.knowledge_builtins()
    if builtins:
        with st.expander("Tài liệu có sẵn"):
            for item in builtins:
                st.text(f"{item.original_filename} · Sẵn sàng")
