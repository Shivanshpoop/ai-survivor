import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.api.routes import router, AUTONOMY_STATE
from app.services.treasury_engine import initialize_treasury, check_survival_condition, get_total_capital
from app.agents.supreme_manager import execute_autonomous_cycle
from app.services.telegram_notifier import send_telegram_alert

async def autonomous_background_loop():
    while True:
        await asyncio.sleep(max(15, settings.AUTO_CYCLE_INTERVAL_SECONDS))
        if not AUTONOMY_STATE.get("auto_run_enabled", False):
            continue
        db = SessionLocal()
        try:
            state = check_survival_condition(db)
            total_cap = get_total_capital(db, state)
            # Hard safety brake: pause auto-loop if total capital drops near emergency reserve (INR 1,300)
            if state.survival_status == "DESTROYED" or total_cap <= (state.emergency_reserve + 300.0):
                AUTONOMY_STATE["auto_run_enabled"] = False
                await send_telegram_alert(f"🚨 AI SURVIVOR AUTO-PAUSED: Capital at INR {total_cap:.2f} (Reserve Guard Triggered).")
                continue
            res = await execute_autonomous_cycle(db)
            await send_telegram_alert(
                f"⚡ AI SURVIVOR Cycle #{res.get('cycle')} Complete\n"
                f"Status: {res.get('survival_status')} | Capital: INR {res.get('total_capital', 0):.2f}"
            )
        except Exception:
            pass
        finally:
            db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        initialize_treasury(db)
    finally:
        db.close()
    task = asyncio.create_task(autonomous_background_loop())
    yield
    task.cancel()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
