import shutil
import secrets
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.core.config import settings
from app.models.domain import Agent, LedgerEntry, AuditLog, Opportunity, AgentMessage, DeliverableArtifact, PaperBacktest, RealOrder, WorkerTask
from app.services.treasury_engine import (
    check_survival_condition,
    get_total_capital,
    get_active_agent_balances,
    create_agent_with_budget,
    allocate_funds_to_agent,
    record_expense,
    record_revenue,
    suspend_and_recall,
    write_audit,
)
from app.agents.supreme_manager import execute_autonomous_cycle
from app.services.telegram_notifier import send_telegram_alert, register_telegram_commands_and_webhook

router = APIRouter()
AUTONOMY_STATE = {"auto_run_enabled": True}

class CreateAgentPayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    role: str = Field(..., min_length=2, max_length=50)
    mission: str = Field(..., min_length=5, max_length=500)
    initial_budget: float = Field(..., ge=0.0)
    risk_score: float = Field(default=20.0, ge=0.0, le=100.0)
    idempotency_key: Optional[str] = None

class AllocationPayload(BaseModel):
    agent_id: str
    amount: float = Field(..., gt=0.0)
    reason: str = Field(..., min_length=3)
    idempotency_key: Optional[str] = None

class ExpensePayload(BaseModel):
    agent_id: str
    amount: float = Field(..., gt=0.0)
    description: str = Field(..., min_length=3)
    idempotency_key: Optional[str] = None

class RevenuePayload(BaseModel):
    agent_id: str
    amount: float = Field(..., gt=0.0)
    description: str = Field(..., min_length=3)
    verified_real_cash: bool = False
    idempotency_key: Optional[str] = None

class UpiClaimPayload(BaseModel):
    artifact_id: str
    buyer_email: str = Field(..., min_length=5)
    utr_number: str = Field(..., min_length=10, max_length=30)
    shipping_address: str = Field(default="Digital Delivery")

class WorkerResultPayload(BaseModel):
    status: str = "COMPLETED"
    result_note: str = ""

@router.get("/store")
def public_store_page():
    return FileResponse("static/store.html")

@router.get("/api/store/catalog")
def get_public_catalog(db: Session = Depends(get_db)):
    items = db.query(DeliverableArtifact).order_by(DeliverableArtifact.created_at.desc()).all()
    seen_slugs = set()
    unique_items = []
    for d in items:
        if d.file_name not in seen_slugs:
            seen_slugs.add(d.file_name)
            upi_uri = (
                f"upi://pay?pa={urllib.parse.quote(settings.FAMPAY_UPI_ID)}"
                f"&pn={urllib.parse.quote(settings.FAMPAY_PAYEE_NAME)}"
                f"&am={d.suggested_price_inr:.2f}&cu=INR"
                f"&tn={urllib.parse.quote(d.file_name[:25])}"
            )
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(upi_uri)}"
            unique_items.append({
                "id": d.id,
                "title": d.title,
                "artifact_type": d.artifact_type,
                "file_name": d.file_name,
                "price_inr": d.suggested_price_inr,
                "pitch_copy": d.pitch_copy,
                "upi_id": settings.FAMPAY_UPI_ID,
                "upi_uri": upi_uri,
                "qr_url": qr_url,
                "units_sold": d.units_sold or 0,
            })
    return {
        "store_name": "NovaCraft Studio",
        "upi_id": settings.FAMPAY_UPI_ID,
        "business_email": settings.BUSINESS_EMAIL,
        "products": unique_items,
    }

@router.post("/api/store/claim-upi")
async def submit_fampay_upi_order(payload: UpiClaimPayload, db: Session = Depends(get_db)):
    utr = "".join(ch for ch in payload.utr_number.strip().upper() if ch.isalnum())
    if len(utr) < 10:
        raise HTTPException(status_code=400, detail="Enter valid 12-digit UPI UTR Reference Number")

    existing = db.query(RealOrder).filter(RealOrder.payment_ref == utr).first()
    if existing:
        return {
            "order_id": existing.id,
            "status": existing.status,
            "download_url": f"/api/store/fulfill/{existing.download_token}" if existing.status == "PAID_DELIVERED" else "",
        }

    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == payload.artifact_id).first()
    if not art:
        raise HTTPException(status_code=404, detail="Product not found")

    order = RealOrder(
        payment_ref=utr,
        artifact_id=art.id,
        buyer_email=payload.buyer_email.strip(),
        shipping_address=(payload.shipping_address or "Digital Delivery").strip(),
        amount_inr=art.suggested_price_inr,
        status="PENDING_UPI_VERIFY",
    )
    db.add(order)
    write_audit(db, "NOVACRAFT_STORE", "UPI_PAYMENT_PENDING", f"Order {order.id}: UTR {utr} | {art.file_name} (INR {art.suggested_price_inr:.2f})")
    db.commit()
    db.refresh(order)

    approve_url = f"{settings.PUBLIC_STORE_URL}/api/orders/{order.id}/approve-upi?token={urllib.parse.quote(settings.ADMIN_TOKEN)}"
    await send_telegram_alert(
        f"💳 PAYMENT APPROVAL REQUEST (FamPay UPI)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• Order: {order.id}\n"
        f"• Item: {art.file_name} ({art.artifact_type})\n"
        f"• Amount: ₹{art.suggested_price_inr:.2f}\n"
        f"• UTR Ref: {utr}\n"
        f"• Buyer: {order.buyer_email}\n"
        f"• Shipping: {order.shipping_address}\n\n"
        f"👉 Check FamPay & Tap to Approve:\n{approve_url}"
    )

    return {
        "order_id": order.id,
        "status": order.status,
        "message": "Payment UTR received! Verifying in 5-15 seconds...",
    }

@router.get("/api/store/order-status/{order_id}")
def check_order_status(order_id: str, db: Session = Depends(get_db)):
    order = db.query(RealOrder).filter(RealOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_id": order.id,
        "status": order.status,
        "download_url": f"/api/store/fulfill/{order.download_token}" if order.status == "PAID_DELIVERED" else "",
    }

@router.get("/api/orders/{order_id}/approve-upi")
async def approve_upi_order_via_link(order_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    if not settings.ADMIN_TOKEN or not secrets.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized approval token")

    order = db.query(RealOrder).filter(RealOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == "PAID_DELIVERED":
        return HTMLResponse(f"<h2>Already Approved!</h2><p>Order {order.id} is already unlocked.</p>")

    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == order.artifact_id).first()
    agent = db.query(Agent).filter(Agent.id == (art.agent_id if art else "")).first() or db.query(Agent).filter(Agent.status == "ACTIVE").first()
    if not agent:
        raise HTTPException(status_code=400, detail="No active agent found")

    entry = record_revenue(
        db=db,
        agent_id=agent.id,
        amount=order.amount_inr,
        description=f"FAMPAY APPROVED [{order.payment_ref}] {art.file_name if art else order.artifact_id} -> {order.buyer_email}",
        verified_real_cash=True,
        idempotency_key=f"UPI-{order.payment_ref}",
    )

    if art:
        art.units_sold = (art.units_sold or 0) + 1
        if art.artifact_type == "MERCH_POD":
            db.add(WorkerTask(
                task_type="FULFILL_POD_SUPPLIER",
                target_url="https://qikink.com",
                subject=f"POD Fulfillment Order {order.id}: {art.file_name}",
                payload_text=f"Buyer: {order.buyer_email}\nShipping: {order.shipping_address}\nItem: {art.title}",
            ))

    order.status = "PAID_DELIVERED"
    write_audit(db, "FAMPAY_GATE", "PAYMENT_APPROVED", f"Order {order.id} approved: +INR {order.amount_inr:.2f}")
    db.commit()

    await send_telegram_alert(
        f"✅ PAYMENT APPROVED & CREDITED!\n"
        f"• Order: {order.id} | UTR: {order.payment_ref}\n"
        f"• Added: +₹{order.amount_inr:.2f}\n"
        f"• New Capital: ₹{entry.total_capital_after:.2f}\n"
        f"• Buyer receipt/download unlocked!"
    )

    return HTMLResponse(
        f"<div style='font-family:sans-serif;padding:30px;background:#0b0f17;color:#10b981;'>"
        f"<h1>✅ FamPay Payment Approved!</h1>"
        f"<p style='color:#e6edf7;'>Order <b>{order.id}</b> (+₹{order.amount_inr:.2f}) credited to Treasury.<br/>"
        f"New Total Capital: <b>₹{entry.total_capital_after:.2f}</b>.</p></div>"
    )

@router.get("/api/store/fulfill/{download_token}")
def fulfill_paid_order(download_token: str, db: Session = Depends(get_db)):
    order = db.query(RealOrder).filter(RealOrder.download_token == download_token).first()
    if not order or order.status != "PAID_DELIVERED":
        raise HTTPException(status_code=403, detail="Payment pending approval")
    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == order.artifact_id).first()
    if not art:
        raise HTTPException(status_code=404, detail="Product missing")
    target = Path("artifacts") / Path(art.file_name).name
    if not target.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(target, filename=art.file_name)

@router.get("/api/worker/tasks", dependencies=[Depends(verify_admin_token)])
def fetch_pending_worker_tasks(db: Session = Depends(get_db)):
    tasks = db.query(WorkerTask).filter(WorkerTask.status == "PENDING").order_by(WorkerTask.created_at.asc()).limit(10).all()
    return {
        "tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "target_url": t.target_url,
                "subject": t.subject,
                "payload_text": t.payload_text,
            }
            for t in tasks
        ]
    }

@router.post("/api/worker/tasks/{task_id}/complete", dependencies=[Depends(verify_admin_token)])
async def complete_worker_task(task_id: str, payload: WorkerResultPayload, db: Session = Depends(get_db)):
    t = db.query(WorkerTask).filter(WorkerTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    t.status = payload.status
    t.result_note = payload.result_note
    db.commit()
    await send_telegram_alert(f"🤖 LOCAL BROWSER WORKER COMPLETED:\n• Task: {t.task_type}\n• {t.subject}\n• Note: {t.result_note}")
    return {"id": t.id, "status": t.status}

@router.get("/health")
def health():
    return {
        "status": "ok",
        "brand": "NovaCraft Studio",
        "auto_run_enabled": AUTONOMY_STATE["auto_run_enabled"],
    }

@router.post("/api/autonomy/toggle", dependencies=[Depends(verify_admin_token)])
def toggle_autonomy():
    AUTONOMY_STATE["auto_run_enabled"] = not AUTONOMY_STATE["auto_run_enabled"]
    return {"auto_run_enabled": AUTONOMY_STATE["auto_run_enabled"]}

@router.get("/api/telegram/setup", dependencies=[Depends(verify_admin_token)])
async def setup_telegram_endpoint():
    return await register_telegram_commands_and_webhook()

@router.post("/api/telegram/webhook")
async def telegram_webhook(
    req: Request,
    telegram_secret: Optional[str] = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
    db: Session = Depends(get_db),
):
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET.strip()
    if not expected_secret or not telegram_secret or not secrets.compare_digest(telegram_secret, expected_secret):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    allowed_id = str(settings.TELEGRAM_CHAT_ID).strip()
    if not allowed_id:
        raise HTTPException(status_code=503, detail="Telegram control chat is not configured")

    data = await req.json()
    msg = data.get("message") or data.get("edited_message") or {}
    chat_id = str(msg.get("chat", {}).get("id", "")).strip()
    text = (msg.get("text") or "").strip().lower()

    if not chat_id or not text:
        return {"ok": True}

    if chat_id != allowed_id:
        raise HTTPException(status_code=403, detail="Unauthorized Telegram chat")

    if "start" in text or "status" in text:
        state = check_survival_condition(db)
        cap = get_total_capital(db, state)
        pending_tasks = db.query(WorkerTask).filter(WorkerTask.status == "PENDING").count()
        loop_txt = "RUNNING" if AUTONOMY_STATE["auto_run_enabled"] else "PAUSED"
        await send_telegram_alert(
            f"📊 NOVACRAFT AUTONOMOUS CONTROL\n"
            f"• Survival: {state.survival_status}\n"
            f"• Total Capital: ₹{cap:.2f}\n"
            f"• Real Revenue: +₹{state.total_real_revenue:.2f}\n"
            f"• Cycles Done: {state.cycle_count} | Worker Queue: {pending_tasks}\n"
            f"• 30s Auto-Loop: {loop_txt}\n"
            f"• Public Store: {settings.PUBLIC_STORE_URL}",
            target_chat_id=chat_id,
        )
    elif "cycle" in text:
        await send_telegram_alert("⏳ Running autonomous cycle now...", target_chat_id=chat_id)
        res = await execute_autonomous_cycle(db)
        await send_telegram_alert(f"⚡ Cycle #{res.get('cycle')} Executed!\nTotal Capital: ₹{res.get('total_capital', 0):.2f}", target_chat_id=chat_id)
    elif "start 30s" in text or "resume" in text:
        AUTONOMY_STATE["auto_run_enabled"] = True
        await send_telegram_alert("▶️ 30-Second Autonomous Loop STARTED!", target_chat_id=chat_id)
    elif "pause" in text:
        AUTONOMY_STATE["auto_run_enabled"] = False
        await send_telegram_alert("⏸️ 30-Second Autonomous Loop PAUSED.", target_chat_id=chat_id)
    elif "store" in text:
        await send_telegram_alert(f"🛒 Public Storefront:\n{settings.PUBLIC_STORE_URL}\nFamPay UPI: {settings.FAMPAY_UPI_ID}", target_chat_id=chat_id)
    elif "revenue" in text:
        state = check_survival_condition(db)
        orders_count = db.query(RealOrder).filter(RealOrder.status == "PAID_DELIVERED").count()
        await send_telegram_alert(
            f"💰 REVENUE & TREASURY REPORT\n"
            f"• Real Cash Earned: +₹{state.total_real_revenue:.2f}\n"
            f"• Verified Paid Orders: {orders_count}\n"
            f"• Expenses: -₹{state.total_expenses:.2f}\n"
            f"• Paper PnL: +₹{state.simulated_paper_pnl:.2f}",
            target_chat_id=chat_id,
        )
    else:
        await send_telegram_alert("👇 Tap any button from the menu below:", target_chat_id=chat_id)
    return {"ok": True}

@router.get("/api/state", dependencies=[Depends(verify_admin_token)])
def get_system_state(db: Session = Depends(get_db)):
    state = check_survival_condition(db)
    total_cap = get_total_capital(db, state)
    agent_held = get_active_agent_balances(db)
    spendable = max(0.0, round(state.treasury_balance - state.emergency_reserve, 2))

    cycles = max(1, state.cycle_count or 1)
    avg_burn = round(state.total_expenses / cycles, 2)
    runway_cycles = int(total_cap / avg_burn) if avg_burn > 0 else 999

    risk_level = "LOW"
    if state.survival_status == "DESTROYED" or total_cap <= state.emergency_reserve:
        risk_level = "CRITICAL"
    elif total_cap < state.initial_capital * 0.65 or runway_cycles < 25:
        risk_level = "ELEVATED"

    agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
    ledger = db.query(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(40).all()
    opportunities = db.query(Opportunity).order_by(Opportunity.created_at.desc()).limit(15).all()
    artifacts = db.query(DeliverableArtifact).order_by(DeliverableArtifact.created_at.desc()).limit(25).all()
    orders = db.query(RealOrder).order_by(RealOrder.created_at.desc()).limit(20).all()
    backtests = db.query(PaperBacktest).order_by(PaperBacktest.created_at.desc()).limit(15).all()
    messages = db.query(AgentMessage).order_by(AgentMessage.id.desc()).limit(30).all()
    audits = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(25).all()

    return {
        "treasury": {
            "survival_status": state.survival_status,
            "auto_run_enabled": AUTONOMY_STATE["auto_run_enabled"],
            "paper_mode_only": state.paper_mode_only,
            "cycle_count": state.cycle_count or 0,
            "initial_capital": state.initial_capital,
            "treasury_balance": state.treasury_balance,
            "agent_held_balance": agent_held,
            "total_capital": total_cap,
            "emergency_reserve": state.emergency_reserve,
            "spendable_treasury": spendable,
            "total_real_revenue": state.total_real_revenue,
            "total_expenses": state.total_expenses,
            "net_real_pnl": round(state.total_real_revenue - state.total_expenses, 2),
            "simulated_paper_pnl": state.simulated_paper_pnl,
            "avg_burn_per_cycle": avg_burn,
            "runway_cycles": runway_cycles,
            "risk_level": risk_level,
            "destruction_reason": state.destruction_reason,
        },
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "mission": a.mission,
                "allocated_budget": a.allocated_budget,
                "current_balance": a.current_balance,
                "revenue": a.revenue,
                "expenses": a.expenses,
                "simulated_pnl": a.simulated_pnl,
                "performance_score": a.performance_score,
                "risk_score": a.risk_score,
                "tasks_completed": a.tasks_completed or 0,
                "status": a.status,
            }
            for a in agents
        ],
        "artifacts": [
            {
                "id": d.id,
                "agent_name": d.agent_name,
                "title": d.title,
                "artifact_type": d.artifact_type,
                "file_name": d.file_name,
                "suggested_price_inr": d.suggested_price_inr,
                "pitch_copy": d.pitch_copy,
                "payment_link": d.payment_link or "",
                "units_sold": d.units_sold or 0,
            }
            for d in artifacts
        ],
        "orders": [
            {
                "id": o.id,
                "payment_ref": o.payment_ref,
                "buyer_email": o.buyer_email,
                "amount_inr": o.amount_inr,
                "status": o.status,
            }
            for o in orders
        ],
        "backtests": [
            {
                "id": b.id,
                "strategy_name": b.strategy_name,
                "symbol": b.symbol,
                "net_return_pct": b.net_return_pct,
                "win_rate_pct": b.win_rate_pct,
                "max_drawdown_pct": b.max_drawdown_pct,
                "sharpe_ratio": b.sharpe_ratio,
                "verdict": b.verdict,
            }
            for b in backtests
        ],
        "opportunities": [
            {
                "id": o.id,
                "title": o.title,
                "category": o.category,
                "target_market": o.target_market,
                "competitor_gap": o.competitor_gap,
                "business_plan": o.business_plan,
                "estimated_cost": o.estimated_cost,
                "expected_revenue": o.expected_revenue,
                "roi_percent": o.roi_percent,
                "risk_level": o.risk_level,
                "status": o.status,
            }
            for o in opportunities
        ],
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "recipient": m.recipient,
                "message_type": m.message_type,
                "content": m.content,
            }
            for m in messages
        ],
        "ledger": [
            {
                "id": l.id,
                "entry_type": l.entry_type,
                "is_simulated": l.is_simulated,
                "agent_id": l.agent_id,
                "amount": l.amount,
                "treasury_after": l.treasury_after,
                "total_capital_after": l.total_capital_after,
                "description": l.description,
            }
            for l in ledger
        ],
        "audit_logs": [
            {
                "id": g.id,
                "actor": g.actor,
                "action": g.action,
                "details": g.details,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in audits
        ],
    }

@router.get("/api/artifacts/download/{file_name}", dependencies=[Depends(verify_admin_token)])
def download_artifact(file_name: str):
    safe_name = Path(file_name).name
    target = Path("artifacts") / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found.")
    return FileResponse(target, filename=safe_name)

@router.post("/api/cycle/run", dependencies=[Depends(verify_admin_token)])
async def run_cycle(db: Session = Depends(get_db)):
    return await execute_autonomous_cycle(db)

@router.post("/api/agents", dependencies=[Depends(verify_admin_token)])
def create_agent(payload: CreateAgentPayload, db: Session = Depends(get_db)):
    try:
        ag = create_agent_with_budget(
            db=db,
            name=payload.name,
            role=payload.role,
            mission=payload.mission,
            initial_budget=payload.initial_budget,
            risk_score=payload.risk_score,
            idempotency_key=payload.idempotency_key,
        )
        return {"id": ag.id, "name": ag.name, "current_balance": ag.current_balance, "status": ag.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/agents/{agent_id}/allocate", dependencies=[Depends(verify_admin_token)])
def allocate_more(agent_id: str, payload: AllocationPayload, db: Session = Depends(get_db)):
    try:
        entry = allocate_funds_to_agent(
            db=db,
            agent_id=agent_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
        return {"transaction_id": entry.id, "treasury_after": entry.treasury_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/agents/{agent_id}/suspend", dependencies=[Depends(verify_admin_token)])
def suspend_agent(agent_id: str, reason: str = "Suspended by operator", db: Session = Depends(get_db)):
    try:
        ag = suspend_and_recall(db, agent_id, reason)
        return {"id": ag.id, "status": ag.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/ledger/expense", dependencies=[Depends(verify_admin_token)])
def log_expense(payload: ExpensePayload, db: Session = Depends(get_db)):
    try:
        entry = record_expense(
            db=db,
            agent_id=payload.agent_id,
            amount=payload.amount,
            description=payload.description,
            idempotency_key=payload.idempotency_key,
        )
        return {"transaction_id": entry.id, "total_capital_after": entry.total_capital_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/ledger/revenue", dependencies=[Depends(verify_admin_token)])
async def log_revenue(payload: RevenuePayload, db: Session = Depends(get_db)):
    try:
        entry = record_revenue(
            db=db,
            agent_id=payload.agent_id,
            amount=payload.amount,
            description=payload.description,
            verified_real_cash=payload.verified_real_cash,
            idempotency_key=payload.idempotency_key,
        )
        if not entry.is_simulated:
            await send_telegram_alert(f"💰 VERIFIED REAL REVENUE: +INR {entry.amount:.2f} | Total Capital: INR {entry.total_capital_after:.2f}")
        return {
            "transaction_id": entry.id,
            "is_simulated": entry.is_simulated,
            "total_capital_after": entry.total_capital_after,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/system/backup", dependencies=[Depends(verify_admin_token)])
def backup_db():
    db_file = Path("ai_survivor_p1.db")
    if not db_file.exists():
        raise HTTPException(status_code=404, detail="Database file not found yet.")
    Path("backups").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path("backups") / f"novacraft_prod_{ts}.db"
    shutil.copy2(db_file, dest)
    return {"message": "Database backup created", "path": str(dest)}
