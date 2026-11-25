import streamlit as st
from pydantic import ValidationError

from backend.app.schemas.auth import LoginRequest
from frontend.api_client import ApiClient, ApiError, FrontendSettings
from frontend.knowledge import knowledge_library
from frontend.views import budgets, chat, dashboard, transactions

VIEWS = {
    "Tổng quan": dashboard, "Giao dịch": transactions, "Ngân sách": budgets,
    "Chat AI": chat, "Kho tài liệu": knowledge_library,
}


def reset_session(notice: str | None = None) -> None:
    st.session_state.clear()
    if notice:
        st.session_state["login_notice"] = notice
    st.rerun()


def login(base_url: str) -> None:
    _, panel, _ = st.columns([1, 2, 1])
    with panel:
        st.title("MoneyMind AI")
        st.caption("Đăng nhập để xem thu chi và quản lý ngân sách.")
        notice = st.session_state.pop("login_notice", None)
        if notice:
            st.warning(notice)
        with st.form("login", clear_on_submit=True, border=True):
            username = st.text_input("Tên đăng nhập", max_chars=64, placeholder="demo_a")
            password = st.text_input("Mật khẩu", type="password", max_chars=256)
            submit = st.form_submit_button("Đăng nhập", type="primary", width="stretch")
        if submit:
            try:
                with ApiClient(base_url) as client:
                    token = client.login(LoginRequest(username=username.strip(), password=password)).access_token
                with ApiClient(base_url, token) as client:
                    user = client.me()
            except ValidationError:
                st.error("Hãy nhập tên đăng nhập và mật khẩu.")
            except ApiError as error:
                st.error("Tên đăng nhập hoặc mật khẩu chưa đúng." if error.status_code == 401 else str(error))
            else:
                st.session_state["token"] = token
                st.session_state["username"] = user.username
                st.rerun()


def main() -> None:
    st.set_page_config(page_title="MoneyMind AI", layout="wide")
    try:
        backend_url = str(FrontendSettings().backend_url)
    except ValidationError:
        st.error("BACKEND_URL không hợp lệ. Hãy kiểm tra cấu hình Frontend.")
        return
    token = st.session_state.get("token")
    if not token:
        login(backend_url)
        return

    with st.sidebar:
        st.header("MoneyMind AI")
        st.caption(st.session_state["username"])
        view = st.radio("Điều hướng", tuple(VIEWS), label_visibility="collapsed")
        if st.button("Đăng xuất", width="stretch"):
            reset_session()

    try:
        with ApiClient(backend_url, token) as client:
            VIEWS[view](client)
    except ApiError as error:
        if error.status_code == 401:
            reset_session(str(error))
        st.error(str(error))


if __name__ == "__main__":
    main()
