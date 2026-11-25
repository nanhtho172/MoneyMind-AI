from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from backend.app.api import auth, finance
from backend.app.core.config import Settings
from backend.app.core.database import initialize_database, make_engine
from backend.app.core.observability import observe, trace_scope
from backend.app.schemas.auth import HealthResponse
from backend.app.services.document_extraction import DocumentError
from backend.app.services.finance import CategoryNotFound, CategoryTypeMismatch, IdempotencyConflict

if TYPE_CHECKING:
    from backend.app.agent.llm import LLM
    from backend.app.agent.rag import Retriever


def create_app(
    settings: Settings | None = None, *, enable_chat: bool = False,
    llm: "LLM | None" = None, retriever: "Retriever | None" = None,
) -> FastAPI:
    if enable_chat:
        from backend.app.agent.rag import ChromaKnowledge
        from backend.app.api import chat, knowledge
        from backend.app.services.knowledge import KnowledgeService

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured = settings if settings is not None else Settings()
        engine = make_engine(configured.database_url)
        chat_runtime = None
        try:
            initialize_database(engine)
            app.state.settings = configured
            app.state.engine = engine
            app.title = configured.app_name
            if enable_chat:
                vector = ChromaKnowledge(configured, engine)
                app.state.knowledge = KnowledgeService(engine, configured, vector)
                chat_runtime = chat.ChatRuntime(engine, configured, llm, retriever if retriever is not None else vector)
                app.state.chat_runtime = chat_runtime
            yield
        finally:
            try:
                if chat_runtime is not None:
                    chat_runtime.close()
            finally:
                engine.dispose()

    app = FastAPI(title=settings.app_name if settings else "MoneyMind AI", lifespan=lifespan)
    app.include_router(auth.router, prefix="/api")
    app.include_router(finance.router, prefix="/api")
    if enable_chat:
        app.include_router(chat.router, prefix="/api")
        app.include_router(knowledge.router, prefix="/api")

    @app.middleware("http")
    async def request_trace(request: Request, call_next):
        trace_id = uuid4().hex
        with trace_scope(trace_id=trace_id), observe("http.request", operation=request.method) as span:
            response = await call_next(request)
            span.status = str(response.status_code)
            response.headers["X-Trace-ID"] = trace_id
            return response

    @app.get("/health", tags=["System"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.exception_handler(DocumentError)
    async def document_error(_request: Request, error: DocumentError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"detail": {"code": error.code, "message": str(error)}})

    @app.exception_handler(CategoryNotFound)
    @app.exception_handler(CategoryTypeMismatch)
    @app.exception_handler(IdempotencyConflict)
    async def finance_error(_request: Request, error: ValueError) -> JSONResponse:
        error_codes = {
            CategoryNotFound: status.HTTP_404_NOT_FOUND,
            CategoryTypeMismatch: 422,
            IdempotencyConflict: status.HTTP_409_CONFLICT,
        }
        return JSONResponse(status_code=error_codes[type(error)], content={"detail": str(error)})

    return app


app = create_app(enable_chat=True)
