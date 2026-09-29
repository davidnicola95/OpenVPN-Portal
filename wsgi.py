"""Production entry point; initialize the existing schema without replacing data."""
from app import app, init_db

init_db()
