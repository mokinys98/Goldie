from contextlib import asynccontextmanager
from datetime import UTC, datetime

import jwt
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from .db import SessionLocal, engine
from .models import User
from .routers import analytics, auth, bots, collector, feeds, status
from .security import hash_password
from .settings import get_settings
from .websocket import manager


def seed_local_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == settings.local_admin_email))
        if existing is None:
            db.add(
                User(
                    email=settings.local_admin_email,
                    password_hash=hash_password(settings.local_admin_password),
                    role="ADMIN",
                )
            )
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_local_admin()
    yield


app = FastAPI(title="Goldie API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(feeds.router)
app.include_router(collector.router)
app.include_router(status.router)
app.include_router(analytics.router)


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Unexpected server error",
                "details": {"type": type(exc).__name__},
            }
        },
    )


@app.get("/health/live")
def live() -> dict:
    return {"status": "ok", "time": datetime.now(UTC)}


@app.get("/health/ready")
def ready() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@app.websocket("/api/v1/stream")
async def stream(websocket: WebSocket, token: str) -> None:
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
