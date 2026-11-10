"""Shared singletons (avoids circular imports between handlers and engine)."""
from app.lzt import LztClient

lzt = LztClient()