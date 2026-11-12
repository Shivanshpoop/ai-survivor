import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.core.config import settings
from app.models.domain import Agent, LedgerEntry, AuditLog, Opportunity, AgentMessage, DeliverableArtifact, PaperBacktest
from app.services.treasury_engine import (
    check_survival_condition,
    get_total_capital,
    get_active_agent_balances,
    create_agent_with_budget,
    allocate_funds_to_agent,
    record_expense,
    record_revenue,
    suspend_and_recall,
)
from app.agents.supreme_manager import execute_autonomous_cycle

router = APIRouter()

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

@router.get("/health")
def health():
    return {"status": "ok", "phase": "PHASE_4_5_EXECUTION_AND_FINANCE", "paper_mode_only": settings.PAPER_MODE_ONLY}

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
    artifacts = db.query(DeliverableArtifact).order_by(DeliverableArtifact.created_at.desc()).limit(20).all()
    backtests = db.query(PaperBacktest).order_by(PaperBacktest.created_at.desc()).limit(15).all()
    messages = db.query(AgentMessage).order_by(AgentMessage.id.desc()).limit(30).all()
    audits = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(25).all()

    return {
        "treasury": {
            "survival_status": state.survival_status,
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
            }
            for d in artifacts
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
def log_revenue(payload: RevenuePayload, db: Session = Depends(get_db)):
    try:
        entry = record_revenue(
            db=db,
            agent_id=payload.agent_id,
            amount=payload.amount,
            description=payload.description,
            verified_real_cash=payload.verified_real_cash,
            idempotency_key=payload.idempotency_key,
        )
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
    dest = Path("backups") / f"ai_survivor_p4_{ts}.db"
    shutil.copy2(db_file, dest)
    return {"message": "Database backup created", "path": str(dest)}
