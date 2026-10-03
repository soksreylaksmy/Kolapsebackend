import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    activity,
    admin,
    alerts,
    auth,
    camera,
    dashboard,
    elders,
    notifications,
    realtime,
    users,
)
from app.core.config import settings
from app.db.session import Base, engine
from app.services.telegram_polling import telegram_polling_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For student/dev setup.
    # Replace with Alembic migrations before production.
    Base.metadata.create_all(bind=engine)

    # Start Telegram polling.
    telegram_task = asyncio.create_task(
        telegram_polling_loop()
    )

    try:
        yield

    finally:
        # Stop Telegram polling when FastAPI shuts down.
        telegram_task.cancel()

        try:
            await telegram_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Backend API for KOLAPSE elderly fall "
        "monitoring and alert management."
    ),
    lifespan=lifespan,
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# API ROUTES
# =========================================================

for router in [
    auth.router,
    users.router,
    elders.router,
    activity.router,
    alerts.router,
    dashboard.router,
    notifications.router,
    camera.router,
    admin.router,
]:
    app.include_router(
        router,
        prefix=settings.api_prefix,
    )


# =========================================================
# WEBSOCKET
# =========================================================

app.include_router(realtime.router)


# =========================================================
# ROOT / HEALTH
# =========================================================

@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "environment": settings.app_env,
    }