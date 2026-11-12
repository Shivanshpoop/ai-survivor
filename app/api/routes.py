import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.core.config import settings
from app.models.domain import Agent, LedgerEntry, AuditLog, Opportunity, AgentMessage, DeliverableArtifact, PaperBacktest, RealOrder
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
from app.services.telegram_notifier import send_telegram_alert

router = APIRouter()
AUTONOMY_STATE = {"auto_run_enabled": False}

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

class PaymentLinkPayload(BaseModel):
    payment_link: str

class PublicCheckoutPayload(BaseModel):
    artifact_id: str
    buyer_email: str
    payment_ref: str

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
            unique_items.append({
                "id": d.id,
                "title": d.title,
                "artifact_type": d.artifact_type,
                "file_name": d.file_name,
                "price_inr": d.suggested_price_inr,
                "pitch_copy": d.pitch_copy,
                "payment_link": d.payment_link or "",
                "units_sold": d.units_sold or 0,
                "built_by": d.agent_name,
            })
    return {"store_name": "AI SURVIVOR Digital Tools & Automation Store", "products": unique_items}

@router.post("/api/artifacts/{artifact_id}/payment-link", dependencies=[Depends(verify_admin_token)])
def set_artifact_payment_link(artifact_id: str, payload: PaymentLinkPayload, db: Session = Depends(get_db)):
    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == artifact_id).first()
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    art.payment_link = payload.payment_link.strip()
    db.commit()
    return {"id": art.id, "payment_link": art.payment_link}

@router.post("/api/payments/webhook")
async def automated_payment_webhook(
    payload: PublicCheckoutPayload,
    x_webhook_secret: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if x_webhook_secret != settings.PAYMENT_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid payment webhook secret")

    existing = db.query(RealOrder).filter(RealOrder.payment_ref == payload.payment_ref.strip()).first()
    if existing:
        return {
            "status": "ALREADY_FULFILLED",
            "order_id": existing.id,
            "download_url": f"/api/store/fulfill/{existing.download_token}",
        }

    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == payload.artifact_id).first()
    if not art:
        raise HTTPException(status_code=404, detail="Product not found")

    agent = db.query(Agent).filter(Agent.id == art.agent_id).first()
    if not agent:
        agent = db.query(Agent).filter(Agent.status == "ACTIVE").first()
    if not agent:
        raise HTTPException(status_code=400, detail="No active agent available to credit revenue")

    entry = record_revenue(
        db=db,
        agent_id=agent.id,
        amount=art.suggested_price_inr,
        description=f"REAL SALE [{payload.payment_ref}] {art.file_name} -> {payload.buyer_email}",
        verified_real_cash=True,
        idempotency_key=f"PAY-{payload.payment_ref.strip()}",
    )

    art.units_sold = (art.units_sold or 0) + 1
    order = RealOrder(
        payment_ref=payload.payment_ref.strip(),
        artifact_id=art.id,
        buyer_email=payload.buyer_email.strip(),
        amount_inr=art.suggested_price_inr,
    )
    db.add(order)
    write_audit(db, "PAYMENT_GATEWAY", "REAL_SALE_FULFILLED", f"Order {order.id}: +INR {art.suggested_price_inr:.2f} for {art.file_name}")
    db.commit()
    db.refresh(order)

    await send_telegram_alert(
        f"💰 REAL CUSTOMER SALE RECEIVED!\n"
        f"Product: {art.file_name}\n"
        f"Amount: +₹{art.suggested_price_inr:.2f}\n"
        f"Buyer: {order.buyer_email}\n"
        f"New Total Capital: ₹{entry.total_capital_after:.2f}"
    )

    return {
        "status": "FULFILLED",
        "order_id": order.id,
        "download_url": f"/api/store/fulfill/{order.download_token}",
        "total_capital": entry.total_capital_after,
    }

@router.get("/api/store/fulfill/{download_token}")
def fulfill_paid_order(download_token: str, db: Session = Depends(get_db)):
    order = db.query(RealOrder).filter(RealOrder.download_token == download_token).first()
    if not order:
        raise HTTPException(status_code=404, detail="Invalid or expired download token")
    art = db.query(DeliverableArtifact).filter(DeliverableArtifact.id == order.artifact_id).first()
    if not art:
        raise HTTPException(status_code=404, detail="Product file missing")
    target = Path("artifacts") / Path(art.file_name).name
    if not target.exists():
        raise HTTPException(status_code=404, detail="File regenerated on next cycle; contact support with Order ID " + order.id)
    return FileResponse(target, filename=art.file_name)

@router.get("/health")
def health():
    return {
        "status": "ok",
        "phase": "REAL_PRODUCTION_STORE_AND_WEBHOOK",
        "auto_run_enabled": AUTONOMY_STATE["auto_run_enabled"],
        "paper_mode_only": settings.PAPER_MODE_ONLY,
    }

@router.post("/api/autonomy/toggle", dependencies=[Depends(verify_admin_token)])
def toggle_autonomy():
    AUTONOMY_STATE["auto_run_enabled"] = not AUTONOMY_STATE["auto_run_enabled"]
    return {"auto_run_enabled": AUTONOMY_STATE["auto_run_enabled"]}

@router.post("/api/telegram/webhook")
async def telegram_webhook(req: Request, db: Session = Depends(get_db)):
    data = await req.json()
    msg = data.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip().lower()
    if settings.TELEGRAM_CHAT_ID and chat_id != str(settings.TELEGRAM_CHAT_ID):
        return {"ok": False}

    if text == "/status":
        state = check_survival_condition(db)
        cap = get_total_capital(db, state)
        await send_telegram_alert(
            f"📊 AI SURVIVOR STATUS\nState: {state.survival_status}\nCapital: INR {cap:.2f}\n"
            f"Real Revenue: INR {state.total_real_revenue:.2f}\nCycles: {state.cycle_count}\nStore: {settings.PUBLIC_STORE_URL}"
        )
    elif text == "/cycle":
        res = await execute_autonomous_cycle(db)
        await send_telegram_alert(f"⚡ Cycle #{res.get('cycle')} executed. Total Capital: INR {res.get('total_capital', 0):.2f}")
    elif text == "/pause":
        AUTONOMY_STATE["auto_run_enabled"] = False
        await send_telegram_alert("⏸️ Autonomous 24/7 loop PAUSED.")
    elif text == "/resume":
        AUTONOMY_STATE["auto_run_enabled"] = True
        await send_telegram_alert("▶️ Autonomous 24/7 loop RESUMED.")
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
    res = await execute_autonomous_cycle(db)
    await send_telegram_alert(
        f"⚡ AI SURVIVOR Cycle #{res.get('cycle')} Complete | Capital: INR {res.get('total_capital', 0):.2f}"
    )
    return res

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
    dest = Path("backups") / f"ai_survivor_real_{ts}.db"
    shutil.copy2(db_file, dest)
    return {"message": "Database backup created", "path": str(dest)}
