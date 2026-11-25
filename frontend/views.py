import re
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

from backend.app.core.calendar import LOCAL_TIME_ZONE, local_today, month_dates
from backend.app.core.formatting import money
from backend.app.schemas.chat import (
    ChatConfirmation, ChatRequest, ChatResponse, ConversationHistory, Decision, PendingBudget, PendingTransaction,
)
from backend.app.schemas.finance import (
    BudgetQuery, BudgetSet, BudgetStatus, BudgetView, CategorySpending, CategoryView, DateRange,
    FinancialSummary, TransactionCreate, TransactionPage, TransactionQuery, TransactionType,
    TransactionView,
)
from frontend.api_client import ApiClient, ApiError

TYPE_NAMES = {TransactionType.INCOME: "Khoản thu", TransactionType.EXPENSE: "Khoản chi"}
ALERT_NAMES = {"NORMAL": "Bình thường", "WARNING": "Gần hạn mức", "EXCEEDED": "Đã chạm hạn mức"}


def month_picker(key: str) -> tuple[int, int]:
    today = local_today()
    first, second = st.columns(2)
    month = first.selectbox("Tháng", range(1, 13), index=today.month - 1, key=f"{key}_month")
    year = second.number_input("Năm", min_value=1, max_value=9999, value=today.year, key=f"{key}_year")
    return year, month


def period_for(year: int, month: int) -> DateRange:
    start, end = month_dates(year, month)
    return DateRange(start_date=start, end_date=end)


def category_names(categories: list[CategoryView]) -> dict[int, str]:
    return {item.id: item.name for item in categories}


def summary_metrics(summary: FinancialSummary) -> None:
    income, expense, net = st.columns(3)
    income.metric("Thu nhập", money(summary.total_income), border=True)
    expense.metric("Chi tiêu", money(summary.total_expense), border=True)
    net.metric("Dòng tiền ròng", money(summary.net_cash_flow), border=True)


def spending_chart(spending: list[CategorySpending]) -> None:
    if not spending:
        st.info("Kỳ này chưa có khoản chi.")
        return
    st.bar_chart(
        [{"Danh mục": item.category_name, "Chi tiêu": item.total_expense} for item in spending],
        x="Danh mục", y="Chi tiêu", y_label="VNĐ", color="#087A69", horizontal=True, sort="-Chi tiêu",
    )


def transaction_table(page: TransactionPage, names: dict[int, str]) -> None:
    if not page.items:
        st.info("Không có giao dịch trong kỳ đã chọn.")
        return
    st.dataframe(
        [
            {
                "Ngày": item.transaction_date.strftime("%d/%m/%Y"),
                "Loại": TYPE_NAMES[item.type],
                "Danh mục": names.get(item.category_id, str(item.category_id)),
                "Số tiền": money(item.amount), "Ghi chú": item.note or "",
            }
            for item in page.items
        ],
        hide_index=True, width="stretch",
    )


def budget_table(rows: list[BudgetStatus]) -> None:
    if not rows:
        st.info("Kỳ này chưa có ngân sách.")
        return
    st.dataframe(
        [
            {
                "Danh mục": row.category_name, "Hạn mức": money(row.amount),
                "Đã chi": money(row.spent), "Còn lại": money(row.remaining),
                "Đã dùng": f"{row.usage_percent:.1f}%", "Trạng thái": ALERT_NAMES[row.alert],
            }
            for row in rows
        ],
        hide_index=True, width="stretch",
    )


def dashboard(client: ApiClient) -> None:
    st.title("Tổng quan tài chính")
    year, month = month_picker("dashboard")
    period = period_for(year, month)
    summary_metrics(client.summary(period))
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Chi tiêu theo danh mục")
        spending_chart(client.spending(period))
    with right:
        st.subheader("Giao dịch gần đây")
        query = TransactionQuery(**period.model_dump(), page_size=5)
        transaction_table(client.transactions(query), category_names(client.categories()))


def parse_amount(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,19}", value.strip()):
        raise ValueError("Nhập số tiền nguyên dương bằng chữ số, ví dụ 35000.")
    return int(value)


def transaction_form(client: ApiClient, categories: list[CategoryView]) -> None:
    st.subheader("Thêm giao dịch")
    if not categories:
        st.info("Chưa có danh mục. Hãy chạy script seed trước.")
        return
    attempt_number = st.session_state.get("transaction_form_number", 0)
    with st.form(f"transaction_form_{attempt_number}", border=True):
        selected = st.selectbox(
            "Danh mục giao dịch", categories, format_func=lambda item: f"{item.name} · {TYPE_NAMES[item.type]}",
        )
        first, second = st.columns(2)
        amount = first.text_input("Số tiền (VNĐ)", max_chars=19, placeholder="35000")
        when = second.date_input("Ngày giao dịch", value=local_today(), format="DD/MM/YYYY")
        note = st.text_input("Ghi chú", max_chars=500)
        submitted = st.form_submit_button("Lưu giao dịch", type="primary")
    if not submitted:
        return
    try:
        request = TransactionCreate(
            category_id=selected.id, type=selected.type, amount=parse_amount(amount),
            transaction_date=when, note=note.strip() or None,
        )
    except (ValidationError, ValueError):
        st.error("Hãy nhập số tiền nguyên dương hợp lệ bằng chữ số, ví dụ 35000.")
        return
    signature = request.model_dump_json()
    previous, key = st.session_state.get("transaction_attempt", (None, None))
    if signature != previous:
        key = f"ui:{uuid4()}"
        st.session_state["transaction_attempt"] = (signature, key)
    saved = client.create_transaction(request.model_copy(update={"idempotency_key": key}))
    st.session_state.pop("transaction_attempt", None)
    st.session_state["transaction_form_number"] = attempt_number + 1
    st.session_state["transaction_notice"] = f"Đã lưu giao dịch #{saved.id} · {money(saved.amount)}."
    st.rerun()


def transactions(client: ApiClient) -> None:
    st.title("Giao dịch")
    notice = st.session_state.pop("transaction_notice", None)
    if notice:
        st.success(notice)
    year, month = month_picker("transactions")
    kind = st.selectbox(
        "Loại giao dịch", [None, *TYPE_NAMES], format_func=lambda value: TYPE_NAMES.get(value, "Tất cả"),
    )
    scope = (year, month, kind)
    if scope != st.session_state.get("transaction_scope"):
        st.session_state["transaction_scope"] = scope
        st.session_state["transaction_page"] = 1
    page = st.session_state["transaction_page"]
    result = client.transactions(TransactionQuery(**period_for(year, month).model_dump(), type=kind, page=page))
    categories = client.categories()
    transaction_table(result, category_names(categories))
    previous, count, following = st.columns([1, 3, 1])
    count.caption(f"Trang {result.page} · {result.total} giao dịch")
    if previous.button("Trang trước", disabled=page == 1):
        st.session_state["transaction_page"] -= 1
        st.rerun()
    if following.button("Trang sau", disabled=page * result.page_size >= result.total):
        st.session_state["transaction_page"] += 1
        st.rerun()
    transaction_form(client, categories)


def budgets(client: ApiClient) -> None:
    st.title("Ngân sách")
    notice = st.session_state.pop("budget_notice", None)
    if notice:
        st.success(notice)
    year, month = month_picker("budget")
    budget_table(client.budget_status(BudgetQuery(year=year, month=month)))
    categories = [item for item in client.categories() if item.type == TransactionType.EXPENSE]
    st.subheader("Đặt hạn mức")
    if not categories:
        st.info("Chưa có danh mục chi. Hãy chạy script seed trước.")
        return
    with st.form("budget_form", border=True):
        category = st.selectbox("Danh mục ngân sách", categories, format_func=lambda item: item.name)
        amount = st.text_input("Hạn mức (VNĐ)", max_chars=19, placeholder="1000000")
        submit = st.form_submit_button("Lưu hạn mức", type="primary")
    if not submit:
        return
    try:
        request = BudgetSet(category_id=category.id, amount=parse_amount(amount), year=year, month=month)
    except (ValidationError, ValueError):
        st.error("Hãy nhập hạn mức nguyên dương hợp lệ bằng chữ số.")
        return
    saved = client.set_budget(request)
    st.session_state["budget_notice"] = f"Đã lưu hạn mức {money(saved.amount)} cho {category.name}."
    st.rerun()


def pending_controls(client: ApiClient, response: ChatResponse) -> None:
    action = response.pending_action
    if action is None:
        st.error("Backend chưa trả bản nháp cần xác nhận.")
        return
    thread_id = response.thread_id
    with st.container(border=True):
        if isinstance(action, PendingTransaction):
            current = action.payload
            st.subheader("Xác nhận giao dịch")
            if response.draft_version and response.draft_version > 1:
                st.caption(f"Bản nháp phiên bản {response.draft_version}")
            st.text(f"{TYPE_NAMES[current.type]} · {action.category} · {money(current.amount)}")
            st.text(f"Ngày {current.transaction_date:%d/%m/%Y}")
            if current.note:
                st.text(current.note)
        elif isinstance(action, PendingBudget):
            current = action.payload
            st.subheader("Xác nhận hạn mức")
            st.text(f"{action.category} · {money(current.amount)} · Tháng {current.month}/{current.year}")
        first, second, third = st.columns(3)
        decision: Decision | None = None
        if first.button("Xác nhận", key=f"confirm_{thread_id}", type="primary"):
            decision = "CONFIRM"
        if second.button("Hủy", key=f"cancel_{thread_id}"):
            decision = "CANCEL"
        refresh = third.button("Kiểm tra trạng thái", key=f"refresh_{thread_id}")
    if decision or refresh:
        run_decision(client, response, decision)


def run_decision(client: ApiClient, response: ChatResponse, decision: Decision | None) -> None:
    try:
        if decision:
            client.confirm(response.thread_id, ChatConfirmation(decision=decision))
        else:
            client.chat_state(response.thread_id)
    except ApiError as error:
        if error.status_code == 401:
            raise
        if error.status_code in {None, 409, 503} and decision:
            try:
                state = client.chat_state(response.thread_id)
            except ApiError as state_error:
                if state_error.status_code == 401:
                    raise
            else:
                if state.status == "COMPLETED":
                    st.rerun()
        st.error(str(error))
        return
    st.rerun()


def render_chat_output(client: ApiClient, response: ChatResponse) -> None:
    if response.status == "ERROR":
        st.error(response.message)
    elif response.status == "NEEDS_CLARIFICATION":
        st.warning(response.message)
    else:
        st.text(response.message)
    receipt = response.structured_data
    if isinstance(receipt, TransactionView):
        st.success(f"Biên nhận #{receipt.id} · {money(receipt.amount)} · {receipt.transaction_date:%d/%m/%Y}")
    elif isinstance(receipt, BudgetView):
        st.success(f"Biên nhận #{receipt.id} · {money(receipt.amount)} · Tháng {receipt.month}/{receipt.year}")

    financial = response.financial_data
    if isinstance(financial, FinancialSummary):
        summary_metrics(financial)
    elif isinstance(financial, TransactionPage):
        transaction_table(financial, category_names(client.categories()) if financial.items else {})
    elif isinstance(financial, list) and financial:
        if isinstance(financial[0], BudgetStatus):
            budget_table(financial)
        else:
            spending_chart(financial)
    if response.sources:
        with st.expander("Nguồn tham khảo", expanded=True):
            for number, source in enumerate(response.sources, 1):
                page = f" · Trang {source.page_number}" if source.page_number else ""
                title = source.original_filename or source.document_title or source.title
                name = source.source_name or source.source
                label = f"{title} · {name}" if name != title else title
                st.text(f"[{number}] {label}{page}")
                if source.source_url:
                    st.link_button(f"Mở nguồn [{number}]", str(source.source_url))
                if source.evidence:
                    st.text(source.evidence)


def chat(client: ApiClient) -> None:
    st.title("Chat AI")
    items = client.conversations()
    ids = {item.conversation_id for item in items}
    selected = st.session_state.get("chat_selected")
    if selected not in ids:
        selected = items[0].conversation_id if items else None
    with st.sidebar:
        if st.button("Cuộc trò chuyện mới"):
            st.session_state.chat_selected = client.reset_conversation().conversation_id
            st.session_state.pop("chat_delete", None)
            st.session_state.chat_pages = 1
            st.rerun()
        if items:
            st.subheader("Lịch sử trò chuyện")
        for item in items:
            key = item.conversation_id
            open_col, delete_col = st.columns([4, 1])
            if open_col.button(item.title, key=f"open_{key}", type="primary" if key == selected else "secondary"):
                st.session_state.chat_selected = key
                st.session_state.chat_pages = 1
                st.session_state.pop("chat_delete", None)
                st.rerun()
            if delete_col.button("Xóa", key=f"delete_{key}"):
                st.session_state.chat_delete = key
            st.caption(item.updated_at.astimezone(LOCAL_TIME_ZONE).strftime("%d/%m/%Y %H:%M")
                       if item.updated_at else "Hội thoại cũ · chưa có mốc cập nhật")
            if st.session_state.get("chat_delete") == key:
                st.warning(f'Xóa cuộc trò chuyện “{item.title}” và các bản nháp đang chờ?')
                if st.button("Xác nhận xóa", key=f"erase_{key}"):
                    client.delete_conversation(key)
                    st.session_state.pop("chat_delete", None)
                    if selected == key:
                        st.session_state.chat_pages = 1
                    st.rerun()
                if st.button("Giữ lại", key=f"keep_{key}"):
                    st.session_state.pop("chat_delete", None)
                    st.rerun()
    history = ConversationHistory()
    if selected:
        st.session_state.chat_selected = selected
        page = client.conversation_page(selected)
        history = page
        for _ in range(1, st.session_state.get("chat_pages", 1)):
            if not page.next_before:
                break
            page = client.conversation_page(selected, page.next_before)
            history.turns = page.turns + history.turns
        if page.next_before and st.button("Tải tin nhắn cũ hơn"):
            st.session_state.chat_pages = st.session_state.get("chat_pages", 1) + 1
            st.rerun()
        pending = history.earlier_pending
        if pending and all(t.response.thread_id != pending.response.thread_id for t in history.turns):
            st.caption("Giao dịch đang chờ từ các tin nhắn trước")
            render_chat_output(client, pending.response)
            if pending.response.pending_action:
                pending_controls(client, pending.response)
    for turn in history.turns:
        with st.chat_message("user"):
            st.text(turn.message)
        with st.chat_message("assistant"):
            render_chat_output(client, turn.response)
            if turn.response.status == "PENDING_CONFIRMATION" and turn.response.pending_state in {
                None, "ready_for_confirmation",
            }:
                pending_controls(client, turn.response)

    prompt = st.chat_input("Bạn muốn hỏi hoặc ghi lại điều gì?", max_chars=1500)
    if prompt:
        try:
            with st.spinner("Đang xử lý…"):
                target = selected or client.reset_conversation().conversation_id
                client.chat(ChatRequest(message=prompt, conversation_id=target))
                st.session_state.chat_selected = target
        except ValidationError:
            st.warning("Hãy nhập nội dung cần xử lý.")
            return
        except ApiError as error:
            if error.status_code == 401:
                raise
            st.error(str(error))
            return
        st.rerun()
