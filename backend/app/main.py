"""The Sonia API: FastAPI app, its routers, and the MCP server mounted at /mcp.

Run locally from backend/:  uvicorn app.main:app --reload
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.profiles import router as profiles_router
from app.api.web_images import router as web_images_router
from app.core.db import close_pool
from app.mcp_client.connections import router as mcp_connections_router
from app.mcp_server.server import MCPMount, build_mcp_app
from app.services.parsing.docling_utils import docling_enabled

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_mcp_mount = MCPMount()


def warm_up_docling():
    # Load Docling's layout models in the background so the first upload isn't slow.
    import threading

    if not docling_enabled():
        return

    def load():
        try:
            from app.services.parsing.docling_utils import _converter
            _converter()
            logger.info("Docling models loaded.")
        except Exception:
            logger.exception("Docling warm-up failed; uploads will fall back to PyMuPDF")

    threading.Thread(target=load, daemon=True).start()


@asynccontextmanager
async def lifespan(_app):
    warm_up_docling()
    # The MCP session manager runs once per app instance, so each lifespan gets a fresh one.
    mcp_app = build_mcp_app()
    async with mcp_app.router.lifespan_context(mcp_app):
        _mcp_mount.app = mcp_app
        try:
            yield
        finally:
            _mcp_mount.app = None
    await close_pool()


app = FastAPI(title="Sonia Advanced RAG API", lifespan=lifespan)
for router in (chat_router, documents_router, conversations_router, profiles_router, web_images_router, mcp_connections_router):
    app.include_router(router)

# Comma-separated, e.g. "https://sonia.vercel.app,http://localhost:3000".
origins = [origin.strip().rstrip("/") for origin in
           os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["General"])
async def root():
    return {"message": "Sonia Advanced RAG Chatbot API is running 🚀", "version": "history-upload-images-v2"}


# MCP for Claude, Cursor and other clients: /mcp and its OAuth metadata at
# /.well-known/oauth-protected-resource/mcp. Mounted last so the API's own routes match first.
app.mount("/", _mcp_mount)
