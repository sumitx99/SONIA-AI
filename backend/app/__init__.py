# Settings from backend/.env must be loaded before any module reads them at import time.
from app.core import config  # noqa: F401
