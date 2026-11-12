"""Unit tests for the treasury engine using an isolated SQLite database."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import settings
from app.models.domain import Agent, LedgerEntry, TreasuryState
from app.services.treasury_engine import (
    allocate_funds_to_agent,
    check_survival_condition,
    create_agent_with_budget,
    get_total_capital,
    initialize_treasury,
    record_expense,
    record_revenue,
)


@pytest.fixture()
def db_session(monkeypatch):
    """Create a fresh in-memory database and deterministic treasury settings."""
    monkeypatch.setattr(settings, "INITIAL_CAPITAL", 5000.0)
    monkeypatch.setattr(settings, "EMERGENCY_RESERVE_RATIO", 0.20)
    monkeypatch.setattr(settings, "MAX_SINGLE_ALLOCATION_RATIO", 0.30)
    monkeypatch.setattr(settings, "PAPER_MODE_ONLY", True)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with test_session() as session:
        yield session

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_initialize_treasury_is_idempotent_and_records_genesis(db_session):
    first = initialize_treasury(db_session)
    second = initialize_treasury(db_session)

    assert first.id == second.id == 1
    assert first.survival_status == "ALIVE"
    assert first.initial_capital == pytest.approx(5000.0)
    assert first.treasury_balance == pytest.approx(5000.0)
    assert first.emergency_reserve == pytest.approx(1000.0)
    assert db_session.query(LedgerEntry).filter_by(entry_type="GENESIS").count() == 1


def test_create_agent_with_budget_moves_funds_from_treasury(db_session):
    agent = create_agent_with_budget(
        db_session,
        name="Market Scout",
        role="RESEARCHER",
        mission="Research legal low-cost business opportunities.",
        initial_budget=300.0,
    )
    state = db_session.query(TreasuryState).filter_by(id=1).one()

    assert agent.status == "ACTIVE"
    assert agent.allocated_budget == pytest.approx(300.0)
    assert agent.current_balance == pytest.approx(300.0)
    assert state.treasury_balance == pytest.approx(4700.0)
    assert get_total_capital(db_session, state) == pytest.approx(5000.0)


def test_allocate_funds_to_agent_records_allocation(db_session):
    agent = create_agent_with_budget(
        db_session,
        name="Product Builder",
        role="PRODUCT_CREATOR",
        mission="Build a small digital product.",
        initial_budget=0.0,
    )

    entry = allocate_funds_to_agent(
        db_session,
        agent_id=agent.id,
        amount=500.0,
        reason="Approved prototype budget",
        idempotency_key="test-allocation-001",
    )
    db_session.refresh(agent)
    state = db_session.query(TreasuryState).filter_by(id=1).one()

    assert entry.entry_type == "ALLOCATION"
    assert entry.amount == pytest.approx(500.0)
    assert agent.current_balance == pytest.approx(500.0)
    assert agent.allocated_budget == pytest.approx(500.0)
    assert state.treasury_balance == pytest.approx(4500.0)


def test_record_expense_reduces_agent_balance_and_tracks_expenses(db_session):
    agent = create_agent_with_budget(
        db_session,
        name="Automation Agent",
        role="SERVICE_BUILDER",
        mission="Build an automation prototype.",
        initial_budget=500.0,
    )

    entry = record_expense(
        db_session,
        agent_id=agent.id,
        amount=125.0,
        description="Simulated prototype operating cost",
    )
    db_session.refresh(agent)
    state = db_session.query(TreasuryState).filter_by(id=1).one()

    assert entry.entry_type == "EXPENSE"
    assert entry.amount == pytest.approx(-125.0)
    assert agent.current_balance == pytest.approx(375.0)
    assert agent.expenses == pytest.approx(125.0)
    assert state.total_expenses == pytest.approx(125.0)
    assert get_total_capital(db_session, state) == pytest.approx(4875.0)


def test_record_revenue_in_paper_mode_never_credits_real_cash(db_session):
    agent = create_agent_with_budget(
        db_session,
        name="Research Agent",
        role="RESEARCHER",
        mission="Evaluate a sample business opportunity.",
        initial_budget=250.0,
    )

    entry = record_revenue(
        db_session,
        agent_id=agent.id,
        amount=200.0,
        description="Paper-mode test result",
        verified_real_cash=True,
    )
    db_session.refresh(agent)
    state = db_session.query(TreasuryState).filter_by(id=1).one()

    assert entry.entry_type == "PAPER_PNL"
    assert entry.is_simulated is True
    assert agent.simulated_pnl == pytest.approx(200.0)
    assert agent.revenue == pytest.approx(0.0)
    assert state.total_real_revenue == pytest.approx(0.0)
    assert state.simulated_paper_pnl == pytest.approx(200.0)
    assert state.treasury_balance == pytest.approx(4750.0)


def test_emergency_reserve_blocks_allocation_and_keeps_system_alive(db_session, monkeypatch):
    # A large reserve ratio makes the spendable amount small while the
    # requested allocation remains below the independent concentration cap.
    monkeypatch.setattr(settings, "EMERGENCY_RESERVE_RATIO", 0.80)
    agent = create_agent_with_budget(
        db_session,
        name="Reserve Test Agent",
        role="RESEARCHER",
        mission="Verify emergency reserve protection.",
        initial_budget=0.0,
    )

    with pytest.raises(ValueError, match="Protected Emergency Reserve"):
        allocate_funds_to_agent(
            db_session,
            agent_id=agent.id,
            amount=1001.0,
            reason="Must be rejected because it invades the reserve",
        )

    state = check_survival_condition(db_session)
    db_session.refresh(agent)

    assert state.survival_status == "ALIVE"
    assert state.treasury_balance == pytest.approx(5000.0)
    assert state.emergency_reserve == pytest.approx(4000.0)
    assert agent.current_balance == pytest.approx(0.0)
    assert get_total_capital(db_session, state) == pytest.approx(5000.0)
