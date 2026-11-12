import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.core.config import settings
from app.models.domain import Agent, LedgerEntry, AuditLog
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
    return {"status": "ok", "phase": "PHASE_1_CORE_ENGINE", "paper_mode_only": settings.PAPER_MODE_ONLY}

@router.get("/api/state", dependencies=[Depends(verify_admin_token)])
def get_system_state(db: Session = Depends(get_db)):
    state = check_survival_condition(db)
    total_cap = get_total_capital(db, state)
    agent_held = get_active_agent_balances(db)
    spendable = max(0.0, round(state.treasury_balance - state.emergency_reserve, 2))

    risk_level = "LOW"
    if state.survival_status == "DESTROYED" or total_cap <= state.emergency_reserve:
        risk_level = "CRITICAL"
    elif total_cap < state.initial_capital * 0.65:
        risk_level = "ELEVATED"

    agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
    ledger = db.query(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(50).all()
    audits = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(40).all()

    return {
        "treasury": {
            "survival_status": state.survival_status,
            "paper_mode_only": state.paper_mode_only,
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
                "status": a.status,
            }
            for a in agents
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
                "created_at": l.created_at.isoformat() if l.created_at else None,
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
    dest = Path("backups") / f"ai_survivor_p1_{ts}.db"
    shutil.copy2(db_file, dest)
    return {"message": "Database backup created", "path": str(dest)}
