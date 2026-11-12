import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, ForeignKey, Text
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class TreasuryState(Base):
    __tablename__ = "treasury_state"
    id = Column(Integer, primary_key=True, default=1)
    survival_status = Column(String, default="ALIVE")
    initial_capital = Column(Float, default=5000.0)
    treasury_balance = Column(Float, default=5000.0)
    emergency_reserve = Column(Float, default=1000.0)
    total_real_revenue = Column(Float, default=0.0)
    total_expenses = Column(Float, default=0.0)
    simulated_paper_pnl = Column(Float, default=0.0)
    paper_mode_only = Column(Boolean, default=False)
    cycle_count = Column(Integer, default=0)
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
    tasks_completed = Column(Integer, default=0)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(String, primary_key=True, default=lambda: f"TXN-{uuid.uuid4().hex[:8].upper()}")
    idempotency_key = Column(String, unique=True, nullable=True)
    entry_type = Column(String, nullable=False)
    is_simulated = Column(Boolean, default=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    amount = Column(Float, nullable=False)
    treasury_after = Column(Float, nullable=False)
    total_capital_after = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(String, primary_key=True, default=lambda: f"OPP-{uuid.uuid4().hex[:6].upper()}")
    title = Column(String, nullable=False)
    category = Column(String, nullable=False)
    target_market = Column(String, default="Indian SMBs & Freelancers")
    competitor_gap = Column(Text, nullable=False)
    business_plan = Column(Text, nullable=False)
    estimated_cost = Column(Float, default=0.0)
    expected_revenue = Column(Float, default=0.0)
    roi_percent = Column(Float, default=0.0)
    risk_level = Column(String, default="LOW")
    status = Column(String, default="RESEARCHED")
    assigned_agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

class DeliverableArtifact(Base):
    __tablename__ = "deliverable_artifacts"
    id = Column(String, primary_key=True, default=lambda: f"ART-{uuid.uuid4().hex[:6].upper()}")
    opportunity_id = Column(String, ForeignKey("opportunities.id"), nullable=True)
    agent_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    artifact_type = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    suggested_price_inr = Column(Float, default=299.0)
    pitch_copy = Column(Text, nullable=False)
    payment_link = Column(String, default="")
    units_sold = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

class RealOrder(Base):
    __tablename__ = "real_orders"
    id = Column(String, primary_key=True, default=lambda: f"ORD-{uuid.uuid4().hex[:8].upper()}")
    payment_ref = Column(String, unique=True, nullable=False)
    artifact_id = Column(String, ForeignKey("deliverable_artifacts.id"), nullable=False)
    buyer_email = Column(String, default="customer@verified.in")
    amount_inr = Column(Float, nullable=False)
    download_token = Column(String, unique=True, default=lambda: uuid.uuid4().hex)
    status = Column(String, default="PAID_DELIVERED")
    created_at = Column(DateTime, default=utcnow)

class PaperBacktest(Base):
    __tablename__ = "paper_backtests"
    id = Column(String, primary_key=True, default=lambda: f"BT-{uuid.uuid4().hex[:6].upper()}")
    strategy_name = Column(String, nullable=False)
    symbol = Column(String, default="NIFTY50-SIM")
    virtual_capital = Column(Float, default=10000.0)
    net_return_pct = Column(Float, default=0.0)
    win_rate_pct = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    verdict = Column(String, default="APPROVED")
    created_at = Column(DateTime, default=utcnow)

class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender = Column(String, nullable=False)
    recipient = Column(String, nullable=False)
    message_type = Column(String, default="DELEGATION")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String, default="CENTRAL_TREASURY")
    action = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
