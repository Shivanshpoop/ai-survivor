import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, ForeignKey, Text
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class TreasuryState(Base):
    __tablename__ = "treasury_state"
    id = Column(Integer, primary_key=True, default=1)
    survival_status = Column(String, default="ALIVE")  # ALIVE | DESTROYED
    initial_capital = Column(Float, default=5000.0)
    treasury_balance = Column(Float, default=5000.0)
    emergency_reserve = Column(Float, default=1000.0)
    total_real_revenue = Column(Float, default=0.0)
    total_expenses = Column(Float, default=0.0)
    simulated_paper_pnl = Column(Float, default=0.0)
    paper_mode_only = Column(Boolean, default=True)
    destruction_reason = Column(Text, nullable=True)
    destroyed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class Agent(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True, default=lambda: f"AGT-{uuid.uuid4().hex[:6].upper()}")
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    mission = Column(Text, nullable=False)
    allocated_budget = Column(Float, default=0.0)
    current_balance = Column(Float, default=0.0)
    revenue = Column(Float, default=0.0)
    expenses = Column(Float, default=0.0)
    simulated_pnl = Column(Float, default=0.0)
    performance_score = Column(Float, default=50.0)
    risk_score = Column(Float, default=20.0)
    status = Column(String, default="ACTIVE")  # ACTIVE | SUSPENDED | DESTROYED
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(String, primary_key=True, default=lambda: f"TXN-{uuid.uuid4().hex[:8].upper()}")
    idempotency_key = Column(String, unique=True, nullable=True)
    entry_type = Column(String, nullable=False)  # GENESIS | ALLOCATION | RECALL | EXPENSE | REVENUE | PAPER_PNL
    is_simulated = Column(Boolean, default=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    amount = Column(Float, nullable=False)
    treasury_after = Column(Float, nullable=False)
    total_capital_after = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String, default="CENTRAL_TREASURY")
    action = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
