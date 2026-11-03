"""Loads backend/.env once, by path, so settings are there whatever directory the server starts from."""

from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")
