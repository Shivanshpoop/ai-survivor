import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.api.routes import router, AUTONOMY_STATE
from app.services.treasury_engine import initialize_treasury, check_survival_condition, get_total_capital
from app.agents.supreme_manager import execute_autonomous_cycle
from app.services.telegram_notifier import register_telegram_commands_and_webhook, update_live_heartbeat, send_telegram_alert

IST = timezone(timedelta(hours=5, minutes=30))

async def autonomous_background_loop():
    await asyncio.sleep(4)
    await register_telegram_commands_and_webhook()
    while True:
        await asyncio.sleep(max(1, settings.AUTO_CYCLE_INTERVAL_SECONDS))
        db = SessionLocal()
        try:
            state = check_survival_condition(db)
            total_cap = get_total_capital(db, state)
            now_ist = datetime.now(IST).strftime("%I:%M:%S %p IST")

            if AUTONOMY_STATE.get("auto_run_enabled", True):
                if state.survival_status == "DESTROYED" or total_cap <= (state.emergency_reserve + 300.0):
                    AUTONOMY_STATE["auto_run_enabled"] = False
                    await send_telegram_alert(f"🚨 RESERVE GUARD TRIGGERED at ₹{total_cap:.2f}. Auto-spend paused to protect ₹1,000 reserve.")
                    continue
                await execute_autonomous_cycle(db)
                state = check_survival_condition(db)
                total_cap = get_total_capital(db, state)

            heartbeat = (
                f"🟢 NOVACRAFT 30s LIVE PULSE ({now_ist})\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• Status: {state.survival_status} | Loop: {'ON (' + str(settings.AUTO_CYCLE_INTERVAL_SECONDS) + 's)' if AUTONOMY_STATE.get('auto_run_enabled') else 'PAUSED'}\n"
                f"• Total Capital: ₹{total_cap:.2f}\n"
                f"• Treasury Cash: ₹{state.treasury_balance:.2f} (Reserve: ₹{state.emergency_reserve:.2f})\n"
                f"• Real Revenue: +₹{state.total_real_revenue:.2f} | Cycles: {state.cycle_count}\n"
                f"• Public Store: {settings.PUBLIC_STORE_URL}"
            )
            await update_live_heartbeat(heartbeat)
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
def natural_public_storefront():
    return FileResponse("static/store.html")

@app.get(settings.HIDDEN_ADMIN_PATH)
def hidden_admin_dashboard():
    return FileResponse("static/index.html")
