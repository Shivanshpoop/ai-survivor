from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.domain import TreasuryState, Agent, LedgerEntry, AuditLog
from app.core.config import settings

def write_audit(db: Session, actor: str, action: str, details: str):
    db.add(AuditLog(actor=actor, action=action, details=details))

def initialize_treasury(db: Session) -> TreasuryState:
    state = db.query(TreasuryState).filter(TreasuryState.id == 1).first()
    if not state:
        initial = round(settings.INITIAL_CAPITAL, 2)
        reserve = round(initial * settings.EMERGENCY_RESERVE_RATIO, 2)
        state = TreasuryState(
            id=1,
            survival_status="ALIVE",
            initial_capital=initial,
            treasury_balance=initial,
            emergency_reserve=reserve,
            paper_mode_only=settings.PAPER_MODE_ONLY,
        )
        db.add(state)
        db.flush()
        db.add(LedgerEntry(
            idempotency_key="GENESIS-INR-5000",
            entry_type="GENESIS",
            is_simulated=False,
            amount=initial,
            treasury_after=initial,
            total_capital_after=initial,
            description=f"Genesis capital initialized: INR {initial:.2f} (Protected Emergency Reserve: INR {reserve:.2f})"
        ))
        write_audit(db, "SYSTEM", "GENESIS_INIT", f"Initialized Central Treasury with INR {initial:.2f}")
        db.commit()
        db.refresh(state)
    return state

def get_active_agent_balances(db: Session) -> float:
    total = db.query(func.coalesce(func.sum(Agent.current_balance), 0.0)).scalar()
    return round(float(total), 2)

def get_total_capital(db: Session, state: TreasuryState) -> float:
    return round(state.treasury_balance + get_active_agent_balances(db), 2)

def check_survival_condition(db: Session) -> TreasuryState:
    state = initialize_treasury(db)
    if state.survival_status == "DESTROYED":
        return state

    total_cap = get_total_capital(db, state)
    if total_cap <= 0.0:
        state.survival_status = "DESTROYED"
        state.treasury_balance = 0.0
        state.destroyed_at = datetime.now(timezone.utc)
        state.destruction_reason = (
            f"DESTRUCTION TRIGGERED: Total available capital reached INR {total_cap:.2f}. "
            f"Cumulative Expenses: INR {state.total_expenses:.2f}, Verified Revenue: INR {state.total_real_revenue:.2f}."
        )
        for ag in db.query(Agent).filter(Agent.status != "DESTROYED").all():
            ag.status = "DESTROYED"
            ag.current_balance = 0.0
        write_audit(db, "SURVIVAL_MONITOR", "AI_SURVIVOR_DESTROYED", state.destruction_reason)
        db.commit()
        db.refresh(state)
    return state

def create_agent_with_budget(
    db: Session,
    name: str,
    role: str,
    mission: str,
    initial_budget: float,
    risk_score: float = 20.0,
    idempotency_key: str = None,
) -> Agent:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        raise ValueError("AI SURVIVOR is DESTROYED. Agent creation permanently halted.")
    if initial_budget < 0:
        raise ValueError("Initial budget cannot be negative.")

    agent = Agent(
        name=name,
        role=role,
        mission=mission,
        allocated_budget=0.0,
        current_balance=0.0,
        risk_score=risk_score,
        status="ACTIVE",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    write_audit(db, "CENTRAL_TREASURY", "AGENT_CREATED", f"Created {agent.name} ({agent.id}) — Role: {role}")

    if initial_budget > 0:
        try:
            allocate_funds_to_agent(
                db=db,
                agent_id=agent.id,
                amount=initial_budget,
                reason=f"Initial budget assignment for {role}",
                idempotency_key=idempotency_key,
            )
        except ValueError:
            db.delete(agent)
            db.commit()
            raise

    db.refresh(agent)
    return agent

def allocate_funds_to_agent(
    db: Session,
    agent_id: str,
    amount: float,
    reason: str,
    idempotency_key: str = None,
) -> LedgerEntry:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        raise ValueError("AI SURVIVOR is DESTROYED. Fund allocation blocked.")
    if amount <= 0:
        raise ValueError("Allocation amount must be greater than zero.")

    if idempotency_key:
        existing = db.query(LedgerEntry).filter(LedgerEntry.idempotency_key == idempotency_key).first()
        if existing:
            return existing

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or agent.status != "ACTIVE":
        raise ValueError("Agent not found or not ACTIVE.")

    spendable_treasury = round(state.treasury_balance - state.emergency_reserve, 2)
    if amount > spendable_treasury:
        raise ValueError(
            f"Requested INR {amount:.2f} exceeds spendable treasury INR {spendable_treasury:.2f} "
            f"(Protected Emergency Reserve: INR {state.emergency_reserve:.2f})."
        )

    max_agent_cap = round(get_total_capital(db, state) * settings.MAX_SINGLE_ALLOCATION_RATIO, 2)
    if (agent.current_balance + amount) > max_agent_cap:
        raise ValueError(
            f"Allocation violates single-agent concentration cap of INR {max_agent_cap:.2f} "
            f"({int(settings.MAX_SINGLE_ALLOCATION_RATIO * 100)}% of total capital)."
        )

    state.treasury_balance = round(state.treasury_balance - amount, 2)
    agent.allocated_budget = round(agent.allocated_budget + amount, 2)
    agent.current_balance = round(agent.current_balance + amount, 2)

    # SessionLocal disables autoflush; persist pending balance changes before
    # aggregate SQL queries so the ledger snapshot reflects the same transaction.
    db.flush()
    total_cap = get_total_capital(db, state)
    entry = LedgerEntry(
        idempotency_key=idempotency_key,
        entry_type="ALLOCATION",
        is_simulated=False,
        agent_id=agent.id,
        amount=round(amount, 2),
        treasury_after=state.treasury_balance,
        total_capital_after=total_cap,
        description=f"Allocated INR {amount:.2f} to {agent.name} ({agent.id}): {reason}",
    )
    db.add(entry)
    write_audit(db, "CENTRAL_TREASURY", "FUNDS_ALLOCATED", entry.description)
    db.commit()
    db.refresh(entry)
    return entry

def record_expense(
    db: Session,
    agent_id: str,
    amount: float,
    description: str,
    idempotency_key: str = None,
) -> LedgerEntry:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        raise ValueError("AI SURVIVOR is DESTROYED.")
    if amount <= 0:
        raise ValueError("Expense amount must be positive.")

    if idempotency_key:
        existing = db.query(LedgerEntry).filter(LedgerEntry.idempotency_key == idempotency_key).first()
        if existing:
            return existing

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or agent.status != "ACTIVE":
        raise ValueError("Agent not found or not ACTIVE.")
    if amount > agent.current_balance:
        raise ValueError(
            f"Budget exceeded: {agent.name} holds INR {agent.current_balance:.2f}, cannot spend INR {amount:.2f}."
        )

    agent.current_balance = round(agent.current_balance - amount, 2)
    agent.expenses = round(agent.expenses + amount, 2)
    state.total_expenses = round(state.total_expenses + amount, 2)

    # Ensure the aggregate balance query sees the agent's reduced cash balance.
    db.flush()
    total_cap = get_total_capital(db, state)
    entry = LedgerEntry(
        idempotency_key=idempotency_key,
        entry_type="EXPENSE",
        is_simulated=False,
        agent_id=agent.id,
        amount=-round(amount, 2),
        treasury_after=state.treasury_balance,
        total_capital_after=total_cap,
        description=f"[{agent.name}] Expense INR {amount:.2f}: {description}",
    )
    db.add(entry)
    write_audit(db, agent.id, "EXPENSE_RECORDED", entry.description)
    db.commit()
    check_survival_condition(db)
    db.refresh(entry)
    return entry

def record_revenue(
    db: Session,
    agent_id: str,
    amount: float,
    description: str,
    verified_real_cash: bool = False,
    idempotency_key: str = None,
) -> LedgerEntry:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        raise ValueError("AI SURVIVOR is DESTROYED.")
    if amount <= 0:
        raise ValueError("Revenue amount must be positive.")

    if idempotency_key:
        existing = db.query(LedgerEntry).filter(LedgerEntry.idempotency_key == idempotency_key).first()
        if existing:
            return existing

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise ValueError("Agent not found.")

    # Enforce strict separation: while PAPER_MODE_ONLY=True, real cash cannot be forged
    is_simulated = True if settings.PAPER_MODE_ONLY else (not verified_real_cash)

    if is_simulated:
        agent.simulated_pnl = round(agent.simulated_pnl + amount, 2)
        state.simulated_paper_pnl = round(state.simulated_paper_pnl + amount, 2)
        entry_type = "PAPER_PNL"
        prefix = "[SIMULATED PAPER RESULT - NOT REAL CASH]"
    else:
        agent.revenue = round(agent.revenue + amount, 2)
        state.total_real_revenue = round(state.total_real_revenue + amount, 2)
        state.treasury_balance = round(state.treasury_balance + amount, 2)
        total_cap_now = get_total_capital(db, state)
        state.emergency_reserve = round(
            max(settings.INITIAL_CAPITAL * settings.EMERGENCY_RESERVE_RATIO, total_cap_now * settings.EMERGENCY_RESERVE_RATIO),
            2,
        )
        entry_type = "REVENUE"
        prefix = "[VERIFIED REAL REVENUE]"

    agent.performance_score = min(100.0, round(agent.performance_score + 5.0, 1))
    total_cap = get_total_capital(db, state)
    entry = LedgerEntry(
        idempotency_key=idempotency_key,
        entry_type=entry_type,
        is_simulated=is_simulated,
        agent_id=agent.id,
        amount=round(amount, 2),
        treasury_after=state.treasury_balance,
        total_capital_after=total_cap,
        description=f"{prefix} [{agent.name}] +INR {amount:.2f}: {description}",
    )
    db.add(entry)
    write_audit(db, agent.id, entry_type, entry.description)
    db.commit()
    db.refresh(entry)
    return entry

def suspend_and_recall(db: Session, agent_id: str, reason: str) -> Agent:
    state = initialize_treasury(db)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise ValueError("Agent not found.")

    recalled = round(agent.current_balance, 2)
    if recalled > 0:
        agent.current_balance = 0.0
        state.treasury_balance = round(state.treasury_balance + recalled, 2)
        db.flush()
        total_cap = get_total_capital(db, state)
        db.add(LedgerEntry(
            entry_type="RECALL",
            is_simulated=False,
            agent_id=agent.id,
            amount=recalled,
            treasury_after=state.treasury_balance,
            total_capital_after=total_cap,
            description=f"Recalled INR {recalled:.2f} from {agent.name} ({agent.id}): {reason}",
        ))

    agent.status = "SUSPENDED"
    write_audit(db, "CENTRAL_TREASURY", "AGENT_SUSPENDED", f"Suspended {agent.name} ({agent.id}): {reason}")
    db.commit()
    db.refresh(agent)
    return agent
