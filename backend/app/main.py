import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .firebase import init_firebase
from .notifications import process_due_reminders
from .routers import ai, days, goals, google, me, sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cyoa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_firebase()
    scheduler = None
    if get_settings().enable_scheduler:
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(process_due_reminders, "interval", seconds=60, id="reminders", max_instances=1, coalesce=True)
        scheduler.start()
        log.info("Reminder scheduler started")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="CYOA API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({*get_settings().frontend_origins, "http://localhost:5173"}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (me.router, goals.router, days.router, google.router, ai.router, sleep.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}
