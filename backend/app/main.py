"""MiraLink Backend - 实时 3D 数字人后端服务"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env before anything else so env vars are available to all modules.
# This covers both direct `python -m uvicorn` launches and subprocess spawns
# where the shell environment doesn't carry .env contents.
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file, override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.ws import router as ws_router
from app.routers.sessions import router as sessions_router
from app.routers.sensor_ws import router as sensor_ws_router
from app.routers.call_ws import router as call_ws_router
from app.routers.diagnostics import router as diagnostics_router
from app.services.warmup import schedule_warmup


@asynccontextmanager
async def lifespan(_: FastAPI):
    schedule_warmup()
    yield

app = FastAPI(
    title="MiraLink Backend",
    description="实时 3D 虚拟形象数字人后端：对话、TTS、行为规划、评测",
    version="0.1.0",
    lifespan=lifespan,
)

# 允许 Unity 跨域连接
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(sessions_router)
app.include_router(sensor_ws_router)
app.include_router(call_ws_router)
app.include_router(diagnostics_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
