import json
import random
import httpx
from sqlalchemy.orm import Session
from app.models.domain import Agent, Opportunity, AgentMessage
from app.services.treasury_engine import (
    initialize_treasury,
    check_survival_condition,
    create_agent_with_budget,
    record_expense,
    record_revenue,
    suspend_and_recall,
    write_audit,
    get_total_capital,
)
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
        "mission": "Identify Python automation gigs, data cleaning tasks, and SMB workflow services.",
        "budget": 600.0,
        "risk": 25.0,
    },
    {
        "name": "Risk & Survival Guardian",
        "role": "RISK_MANAGER",
        "mission": "Monitor capital burn, enforce reserve limits, and halt underperforming agents.",
        "budget": 200.0,
        "risk": 5.0,
    },
]

RESEARCH_DATABASE = [
    {
        "title": "GST Invoice CSV-to-Tally Python Cleaner",
        "category": "AUTOMATION",
        "target_market": "Local Indian CAs & Small Retailers",
        "competitor_gap": "Existing ERP tools are expensive (INR 5,000+/yr); merchants need a fast INR 499 one-time CLI/script.",
        "business_plan": "1. Build Python script normalizing GSTR-1/2B CSV mismatches. 2. Validate with 3 local accountants. 3. Sell license at INR 499.",
        "estimated_cost": 60.0,
        "expected_revenue": 499.0,
        "risk_level": "LOW",
    },
    {
        "title": "AI Prompt & Freelance Proposal Calculator Kit",
        "category": "DIGITAL_PRODUCT",
        "target_market": "College Freelancers & Solo Agencies",
        "competitor_gap": "Generic Notion templates lack Indian pricing tiers and scope-creep clauses.",
        "business_plan": "1. Package 15 tested RFP templates + pricing sheet. 2. List on Gumroad/Topmate at INR 299. 3. Distribute via organic tech communities.",
        "estimated_cost": 40.0,
        "expected_revenue": 299.0,
        "risk_level": "LOW",
    },
    {
        "title": "B2B Lead Deduplication & WhatsApp Format Service",
        "category": "FREELANCING",
        "target_market": "Real Estate & Coaching Institutes",
        "competitor_gap": "Agencies waste hours manually fixing +91 formatting and duplicate Excel rows.",
        "business_plan": "1. Offer 24-hour turnaround batch cleaning via Python pandas script. 2. Charge INR 450 per 5,000 rows.",
        "estimated_cost": 50.0,
        "expected_revenue": 450.0,
        "risk_level": "LOW",
    },
    {
        "title": "NIFTY 50 Volatility Breakout Paper Backtest",
        "category": "PAPER_TRADING",
        "target_market": "Permitted Index Research (Sandbox Only)",
        "competitor_gap": "Retail strategies ignore slippage and strict 1% drawdown caps.",
        "business_plan": "1. Backtest 5-year intraday data in paper mode only. 2. Reject if Sharpe < 1.5. Zero real capital risked.",
        "estimated_cost": 35.0,
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
        f"estimated_cost (number between 25 and 120), expected_revenue (number between 150 and 800), risk_level (LOW or MEDIUM)."
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
                raw = resp.json()["choices"][0]["message"]["content"]
                return json.loads(raw)
    except Exception:
        return None
    return None

def ensure_initial_team(db: Session):
    state = initialize_treasury(db)
    if state.survival_status == "DESTROYED":
        return
    if db.query(Agent).count() == 0:
        for member in INITIAL_TEAM:
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
        db.commit()

async def execute_autonomous_cycle(db: Session) -> dict:
    state = check_survival_condition(db)
    if state.survival_status == "DESTROYED":
        return {"status": "DESTROYED", "reason": state.destruction_reason}

    ensure_initial_team(db)
    state.cycle_count = (state.cycle_count or 0) + 1
    cycle = state.cycle_count
    events = []

    # Step 1: Market Research Agent discovers & scores a new opportunity
    researcher = db.query(Agent).filter(Agent.role == "RESEARCHER", Agent.status == "ACTIVE").first()
    opp_data = await generate_llm_opportunity(cycle)
    if not opp_data:
        opp_data = random.choice(RESEARCH_DATABASE)

    cost = float(opp_data.get("estimated_cost", 50.0))
    rev = float(opp_data.get("expected_revenue", 300.0))
    roi = round(((rev - cost) / max(1.0, cost)) * 100.0, 1)

    opp = Opportunity(
        title=f"{opp_data['title']} [C#{cycle}]",
        category=opp_data.get("category", "AUTOMATION"),
        target_market=opp_data.get("target_market", "Indian SMBs"),
        competitor_gap=opp_data.get("competitor_gap", "High manual effort in existing workflows."),
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

    sender_name = researcher.name if researcher else "SUPREME_MANAGER"
    post_message(
        db,
        sender_name,
        "SUPREME_MANAGER",
        "RESEARCH_REPORT",
        f"Evaluated '{opp.title}' | Est. Cost: INR {cost:.2f} | Expected Rev: INR {rev:.2f} | ROI: {roi}% | Decision: {opp.status}"
    )
    events.append(f"Research completed: {opp.title} (ROI {roi}%, {opp.status})")

    # Step 2: Supreme Manager delegates approved opportunity to best execution agent
    if opp.status == "APPROVED":
        candidates = (
            db.query(Agent)
            .filter(Agent.status == "ACTIVE", Agent.role.in_(["PRODUCT_CREATOR", "SERVICE_BUILDER"]), Agent.current_balance >= cost)
            .all()
        )
        if candidates:
            executor = max(candidates, key=lambda a: a.performance_score)
            opp.assigned_agent_id = executor.id
            opp.status = "COMPLETED"
            executor.tasks_completed = (executor.tasks_completed or 0) + 1

            post_message(
                db,
                "SUPREME_MANAGER",
                executor.name,
                "TASK_DELEGATION",
                f"Execute '{opp.title}'. Authorized spend cap: INR {cost:.2f}. Plan: {opp.business_plan}"
            )

            record_expense(
                db=db,
                agent_id=executor.id,
                amount=cost,
                description=f"Cycle #{cycle} execution & validation cost: {opp.title}",
            )
            events.append(f"Delegated to {executor.name}: spent INR {cost:.2f}")

            # Sandbox validation outcome (78% success rate in paper simulation)
            if random.random() <= 0.78:
                sim_return = round(rev * random.uniform(0.85, 1.15), 2)
                record_revenue(
                    db=db,
                    agent_id=executor.id,
                    amount=sim_return,
                    description=f"Sandbox validation return for '{opp.title}'",
                    verified_real_cash=False,
                )
                post_message(
                    db,
                    executor.name,
                    "SUPREME_MANAGER",
                    "TASK_COMPLETE",
                    f"Completed '{opp.title}'. Simulated validation return: +INR {sim_return:.2f} (Score: {executor.performance_score}/100)."
                )
                events.append(f"{executor.name} logged +INR {sim_return:.2f} (Paper Simulation)")
            else:
                executor.performance_score = max(0.0, round(executor.performance_score - 15.0, 1))
                post_message(
                    db,
                    executor.name,
                    "RISK_MANAGER",
                    "EXPERIMENT_FAILED",
                    f"Experiment '{opp.title}' yielded zero return. Score reduced to {executor.performance_score}/100."
                )
                events.append(f"Experiment yielded 0 return; {executor.name} score -> {executor.performance_score}")

    # Step 3: Risk Guardian audits all active agents and suspends underperformers
    for ag in db.query(Agent).filter(Agent.status == "ACTIVE").all():
        if ag.performance_score < 25.0:
            suspend_and_recall(db, ag.id, f"Performance score {ag.performance_score} below threshold 25.0")
            post_message(
                db,
                "Risk & Survival Guardian",
                "SUPREME_MANAGER",
                "RISK_INTERVENTION",
                f"Suspended {ag.name} ({ag.id}) due to low score ({ag.performance_score}) and recalled remaining balance."
            )
            events.append(f"Risk Guardian suspended {ag.name}")

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
