import json
import random
import httpx
from sqlalchemy.orm import Session
from app.models.domain import Agent, Opportunity, AgentMessage
from app.services.treasury_engine import (
    initialize_treasury,
    check_survival_condition,
    create_agent_with_budget,
    allocate_funds_to_agent,
    record_expense,
    record_revenue,
    suspend_and_recall,
    write_audit,
    get_total_capital,
)
from app.execution.artifact_factory import build_deliverable_artifact, run_paper_strategy_backtest
from app.core.config import settings

INITIAL_TEAM = [
    {
        "name": "Market Research Agent",
        "role": "RESEARCHER",
        "mission": "Discover high-ROI, low-capital niches, analyze competitors, and draft lean business plans.",
        "budget": 400.0,
        "risk": 15.0,
    },
    {
        "name": "Digital Products Agent",
        "role": "PRODUCT_CREATOR",
        "mission": "Build templates, micro-utilities, and downloadable digital assets with near-zero marginal cost.",
        "budget": 500.0,
        "risk": 20.0,
    },
    {
        "name": "Freelancing & Automation Agent",
        "role": "SERVICE_BUILDER",
        "mission": "Build Python automation scripts, data cleaning deliverables, and SMB workflow tools.",
        "budget": 600.0,
        "risk": 25.0,
    },
    {
        "name": "Trading Research Agent",
        "role": "TRADING_RESEARCHER",
        "mission": "Run paper-only backtests with strict stop-loss & drawdown limits. Zero real leverage.",
        "budget": 250.0,
        "risk": 30.0,
    },
    {
        "name": "Risk & Survival Guardian",
        "role": "RISK_MANAGER",
        "mission": "Monitor capital burn, forecast runway, and halt underperforming agents.",
        "budget": 200.0,
        "risk": 5.0,
    },
]

RESEARCH_DATABASE = [
    {
        "title": "GST Invoice CSV-to-Tally Python Cleaner",
        "category": "AUTOMATION",
        "target_market": "Local Indian CAs & Small Retailers",
        "competitor_gap": "Existing ERP tools cost INR 5,000+/yr; merchants need a fast INR 499 one-time CLI tool.",
        "business_plan": "1. Generate Python CSV deduplicator. 2. Package CLI utility. 3. Sell license at INR 499.",
        "estimated_cost": 45.0,
        "expected_revenue": 499.0,
        "risk_level": "LOW",
    },
    {
        "title": "AI Prompt & Freelance Proposal Calculator Kit",
        "category": "DIGITAL_PRODUCT",
        "target_market": "College Freelancers & Solo Agencies",
        "competitor_gap": "Generic Notion templates lack Indian pricing tiers and scope-creep clauses.",
        "business_plan": "1. Generate Markdown/RFP proposal kit. 2. List on Gumroad/Topmate at INR 299.",
        "estimated_cost": 30.0,
        "expected_revenue": 299.0,
        "risk_level": "LOW",
    },
    {
        "title": "B2B Lead Deduplication & WhatsApp Format Service",
        "category": "FREELANCING",
        "target_market": "Real Estate & Coaching Institutes",
        "competitor_gap": "Agencies waste hours manually fixing +91 formatting and duplicate Excel rows.",
        "business_plan": "1. Build +91 phone normalizer script. 2. Deliver batch cleaning at INR 450 per 5,000 rows.",
        "estimated_cost": 40.0,
        "expected_revenue": 450.0,
        "risk_level": "LOW",
    },
    {
        "title": "NIFTY 50 Volatility Breakout Paper Backtest",
        "category": "PAPER_TRADING",
        "target_market": "Permitted Index Research (Sandbox Only)",
        "competitor_gap": "Retail strategies ignore slippage and strict 1.5% stop-loss caps.",
        "business_plan": "1. Run 60-session walk-forward paper simulation. 2. Reject if Sharpe < 1.2 or DD > 8%.",
        "estimated_cost": 25.0,
        "expected_revenue": 160.0,
        "risk_level": "MEDIUM",
    },
]

def post_message(db: Session, sender: str, recipient: str, msg_type: str, content: str):
    db.add(AgentMessage(sender=sender, recipient=recipient, message_type=msg_type, content=content))

async def generate_llm_opportunity(cycle_num: int) -> dict | None:
    if not settings.LLM_API_KEY:
        return None
    prompt = (
        f"You are the Market Research Agent inside AI SURVIVOR (starting capital INR 5000). "
        f"Propose 1 ethical, legal, low-cost micro-business opportunity in India for Cycle #{cycle_num}. "
        f"Return strictly valid JSON with keys: title, category, target_market, competitor_gap, business_plan, "
        f"estimated_cost (number between 25 and 90), expected_revenue (number between 150 and 700), risk_level (LOW or MEDIUM)."
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            if resp.status_code == 200:
                return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception:
        return None
    return None

def ensure_initial_team(db: Session):
    state = initialize_treasury(db)
    if state.survival_status == "DESTROYED":
        return
    existing_roles = {a.role for a in db.query(Agent).all()}
    for member in INITIAL_TEAM:
        if member["role"] not in existing_roles:
            try:
                ag = create_agent_with_budget(
                    db=db,
                    name=member["name"],
                    role=member["role"],
                    mission=member["mission"],
                    initial_budget=member["budget"],
                    risk_score=member["risk"],
                )
                post_message(
                    db,
                    "SUPREME_MANAGER",
                    ag.name,
                    "ONBOARDING",
                    f"Assigned mission: '{ag.mission}' with seed budget INR {ag.current_balance:.2f}."
                )
            except ValueError:
                pass
    db.commit()

async def execute_autonomous_cycle(db: Session) -> dict:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        return {"status": "DESTROYED", "reason": state.destruction_reason}

    ensure_initial_team(db)
    state.cycle_count = (state.cycle_count or 0) + 1
    cycle = state.cycle_count
    events = []

    researcher = db.query(Agent).filter(Agent.role == "RESEARCHER", Agent.status == "ACTIVE").first()
    opp_data = await generate_llm_opportunity(cycle) or random.choice(RESEARCH_DATABASE)

    cost = float(opp_data.get("estimated_cost", 40.0))
    rev = float(opp_data.get("expected_revenue", 300.0))
    roi = round(((rev - cost) / max(1.0, cost)) * 100.0, 1)

    opp = Opportunity(
        title=f"{opp_data['title']} [C#{cycle}]",
        category=opp_data.get("category", "AUTOMATION"),
        target_market=opp_data.get("target_market", "Indian SMBs"),
        competitor_gap=opp_data.get("competitor_gap", "Manual workflow overhead."),
        business_plan=opp_data.get("business_plan", "Build MVP -> Validate -> Monetize."),
        estimated_cost=cost,
        expected_revenue=rev,
        roi_percent=roi,
        risk_level=opp_data.get("risk_level", "LOW"),
        status="APPROVED" if roi >= 150.0 else "REJECTED",
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    post_message(
        db,
        researcher.name if researcher else "SUPREME_MANAGER",
        "SUPREME_MANAGER",
        "RESEARCH_REPORT",
        f"Evaluated '{opp.title}' | Cost: INR {cost:.2f} | Expected Rev: INR {rev:.2f} | ROI: {roi}% | {opp.status}"
    )

    if opp.status == "APPROVED":
        target_roles = ["TRADING_RESEARCHER"] if opp.category == "PAPER_TRADING" else ["PRODUCT_CREATOR", "SERVICE_BUILDER"]
        candidates = (
            db.query(Agent)
            .filter(Agent.status == "ACTIVE", Agent.role.in_(target_roles), Agent.current_balance >= cost)
            .all()
        )
        if not candidates:
            candidates = (
                db.query(Agent)
                .filter(Agent.status == "ACTIVE", Agent.role != "RISK_MANAGER", Agent.current_balance >= cost)
                .all()
            )

        if candidates:
            executor = max(candidates, key=lambda a: a.performance_score)
            opp.assigned_agent_id = executor.id
            opp.status = "COMPLETED"
            executor.tasks_completed = (executor.tasks_completed or 0) + 1

            record_expense(
                db=db,
                agent_id=executor.id,
                amount=cost,
                description=f"Cycle #{cycle} execution cost: {opp.title}",
            )

            if opp.category == "PAPER_TRADING":
                bt = run_paper_strategy_backtest(db, f"NIFTY50-Breakout-C{cycle}")
                post_message(
                    db,
                    executor.name,
                    "SUPREME_MANAGER",
                    "BACKTEST_REPORT",
                    f"Backtest {bt.id}: Return {bt.net_return_pct}% | WinRate {bt.win_rate_pct}% | MaxDD {bt.max_drawdown_pct}% | Sharpe {bt.sharpe_ratio} -> {bt.verdict}"
                )
                if bt.net_return_pct > 0:
                    sim_gain = round(max(40.0, rev * (bt.net_return_pct / 10.0)), 2)
                    record_revenue(db, executor.id, sim_gain, f"Paper backtest return ({bt.id})", verified_real_cash=False)
            else:
                art = build_deliverable_artifact(
                    db=db,
                    opp_id=opp.id,
                    opp_title=opp.title,
                    category=opp.category,
                    agent_name=executor.name,
                    price_inr=rev,
                )
                post_message(
                    db,
                    executor.name,
                    "SUPREME_MANAGER",
                    "ARTIFACT_BUILT",
                    f"Built deliverable '{art.file_name}' ({art.artifact_type}). Ready for commercial listing at INR {rev:.2f}."
                )
                if random.random() <= 0.80:
                    sim_gain = round(rev * random.uniform(0.85, 1.15), 2)
                    record_revenue(db, executor.id, sim_gain, f"Simulated validation for {art.file_name}", verified_real_cash=False)
                else:
                    executor.performance_score = max(0.0, round(executor.performance_score - 12.0, 1))

    # Financial Intelligence: Auto-topup high-performing agent (score >= 70) if balance drops below INR 120
    for ag in db.query(Agent).filter(Agent.status == "ACTIVE").all():
        if ag.performance_score < 25.0:
            suspend_and_recall(db, ag.id, f"Performance score {ag.performance_score} below threshold 25.0")
        elif ag.performance_score >= 70.0 and ag.current_balance < 120.0:
            try:
                allocate_funds_to_agent(db, ag.id, 200.0, "Performance-based reinvestment top-up")
                post_message(db, "SUPREME_MANAGER", ag.name, "REINVESTMENT", "Auto-allocated INR 200.00 reward budget for high performance score.")
            except ValueError:
                pass

    state = check_survival_condition(db)
    total_cap = get_total_capital(db, state)
    write_audit(db, "SUPREME_MANAGER", f"CYCLE_{cycle}_FINISHED", f"Cycle #{cycle} complete. Total Capital: INR {total_cap:.2f}")
    db.commit()

    return {
        "cycle": cycle,
        "survival_status": state.survival_status,
        "total_capital": total_cap,
        "treasury_balance": state.treasury_balance,
        "events": events,
    }
