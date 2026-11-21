"""Web routes package for Central Local Web Dashboard."""

from src.web.routes.items import router as items_router
from src.web.routes.logs import router as logs_router
from src.web.routes.queue import router as queue_router
from src.web.routes.register import router as register_router
from src.web.routes.status import router as status_router

__all__ = [
    "status_router",
    "items_router",
    "queue_router",
    "register_router",
    "logs_router",
]
