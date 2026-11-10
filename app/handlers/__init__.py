from app.handlers import admin, filters, ledger, menu, sessions, wallet

ROUTERS = (menu.router, wallet.router, filters.router, sessions.router, ledger.router, admin.router)