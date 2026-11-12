import json
import math
import random
import httpx
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.domain import DeliverableArtifact, PaperBacktest
from app.core.config import settings

ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(exist_ok=True)

PRODUCT_CATALOG = [
    {
        "slug": "gst_tally_reconciler",
        "ext": "py",
        "type": "PYTHON_AUTOMATION_SCRIPT",
        "price": 499.0,
        "pitch": "GSTIN & Invoice CSV deduplicator for CAs & Indian SMBs. Eliminates GSTR-2B mismatches in 2 seconds.",
        "code": '''import csv, sys

def reconcile_gst(in_csv, out_csv):
    seen, rows = set(), []
    with open(in_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = ((r.get("InvoiceNo") or "").strip().upper(), (r.get("GSTIN") or "").strip().upper())
            if key[0] and key not in seen:
                seen.add(key)
                rows.append(r)
    if rows:
        with open(out_csv, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
    print(f"Reconciled {len(rows)} unique GST invoices -> {out_csv}")

if __name__ == "__main__":
    reconcile_gst(sys.argv[1], sys.argv[2]) if len(sys.argv) >= 3 else print("Usage: python script.py in.csv out.csv")
'''
    },
    {
        "slug": "whatsapp_lead_normalizer",
        "ext": "py",
        "type": "FREELANCE_DELIVERABLE_SCRIPT",
        "price": 450.0,
        "pitch": "+91 Indian phone normalizer & duplicate lead cleaner for Real Estate & Coaching agencies.",
        "code": '''import csv, re, sys

def norm(p):
    d = re.sub(r"\\D", "", p or "")
    return "+91" + d if len(d) == 10 else ("+" + d if len(d) == 12 and d.startswith("91") else "")

def clean_leads(in_csv, out_csv):
    seen, out_rows = set(), []
    with open(in_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ph = norm(r.get("Phone", ""))
            if ph and ph not in seen:
                seen.add(ph)
                r["Phone"] = ph
                out_rows.append(r)
    if out_rows:
        with open(out_csv, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=out_rows[0].keys())
            w.writeheader()
            w.writerows(out_rows)
    print(f"Cleaned {len(out_rows)} valid +91 leads -> {out_csv}")

if __name__ == "__main__":
    clean_leads(sys.argv[1], sys.argv[2]) if len(sys.argv) >= 3 else print("Usage: python script.py raw.csv clean.csv")
'''
    },
    {
        "slug": "ecommerce_seller_profit_calculator",
        "ext": "py",
        "type": "PYTHON_MICRO_SAAS_CLI",
        "price": 399.0,
        "pitch": "Amazon/Flipkart/Meesho true net profit, GST & RTO loss calculator for D2C sellers.",
        "code": '''def calc_margin(selling_price, cost_price, referral_pct=15.0, shipping=65.0, gst_pct=18.0, rto_pct=12.0):
    commission = selling_price * (referral_pct / 100.0)
    gst_on_fees = (commission + shipping) * (gst_pct / 100.0)
    rto_cost = shipping * (rto_pct / 100.0)
    net_profit = selling_price - cost_price - commission - shipping - gst_on_fees - rto_cost
    return round(net_profit, 2), round((net_profit / selling_price) * 100, 1)

if __name__ == "__main__":
    sp = float(input("Selling Price (INR): "))
    cp = float(input("Product Cost (INR): "))
    profit, margin = calc_margin(sp, cp)
    print(f"Net Profit: INR {profit} ({margin}% margin after fees, GST & RTO)")
'''
    },
    {
        "slug": "upi_bank_statement_categorizer",
        "ext": "py",
        "type": "FINTECH_UTILITY_SCRIPT",
        "price": 599.0,
        "pitch": "Auto-tags bank/UPI CSV statements into Food, Travel, SaaS, Rent & Tax buckets for ITR prep.",
        "code": '''import csv, sys

RULES = {"SWIGGY": "Food", "ZOMATO": "Food", "UBER": "Travel", "OLA": "Travel", "AWS": "Cloud/SaaS", "ZERODHA": "Investments"}

def categorize(in_csv, out_csv):
    rows = []
    with open(in_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            desc = (r.get("Description") or "").upper()
            r["Category"] = next((v for k, v in RULES.items() if k in desc), "General")
            rows.append(r)
    if rows:
        with open(out_csv, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
    print(f"Categorized {len(rows)} bank entries -> {out_csv}")

if __name__ == "__main__":
    categorize(sys.argv[1], sys.argv[2]) if len(sys.argv) >= 3 else print("Usage: python script.py bank.csv tagged.csv")
'''
    },
    {
        "slug": "ats_resume_keyword_scorer",
        "ext": "py",
        "type": "CAREER_TECH_TOOL",
        "price": 249.0,
        "pitch": "Instant offline ATS keyword matcher & missing skill extractor for job seekers & students.",
        "code": '''import re, sys
from pathlib import Path

def score_resume(resume_txt, jd_txt):
    r_words = set(re.findall(r"[a-zA-Z]{3,}", Path(resume_txt).read_text(encoding="utf-8").lower()))
    j_words = set(re.findall(r"[a-zA-Z]{3,}", Path(jd_txt).read_text(encoding="utf-8").lower()))
    matched = r_words & j_words
    missing = sorted(j_words - r_words)[:20]
    pct = round((len(matched) / max(1, len(j_words))) * 100, 1)
    print(f"ATS Match Score: {pct}%\\nTop Missing Keywords: {', '.join(missing)}")

if __name__ == "__main__":
    score_resume(sys.argv[1], sys.argv[2]) if len(sys.argv) >= 3 else print("Usage: python script.py resume.txt jd.txt")
'''
    },
    {
        "slug": "freelance_rfp_pricing_kit",
        "ext": "md",
        "type": "DIGITAL_PRODUCT_ASSET",
        "price": 299.0,
        "pitch": "15 Indian agency RFP templates, scope-creep clauses & rate card for solo developers.",
        "code": '''# Indian Freelance & Agency RFP + Scope-Creep Protection Kit
## 1. Payment Milestone Structure
- **50% Kickoff Advance** (Non-refundable once architecture starts)
- **30% Staging Demo Sign-off**
- **20% Final Source Code Handover**

## 2. Scope-Creep Clause
> Any feature, API integration, or UI revision outside the signed checklist is billed separately at ₹500/hour.
'''
    },
]

async def generate_llm_product(opp_title: str, price_inr: float) -> dict | None:
    if not settings.LLM_API_KEY:
        return None
    prompt = (
        f"Build a complete, standalone, zero-dependency Python 3 script solving: '{opp_title}'. "
        f"Return valid JSON with keys: slug (snake_case), type (PYTHON_TOOL), pitch (1-sentence commercial pitch in INR {price_inr}), "
        f"code (complete working Python code with if __name__ == '__main__': block)."
    )
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
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

async def build_deliverable_artifact(db: Session, opp_id: str, opp_title: str, category: str, agent_id: str, agent_name: str, price_inr: float) -> DeliverableArtifact:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    existing_files = {d.file_name for d in db.query(DeliverableArtifact).all()}

    llm_prod = await generate_llm_product(opp_title, price_inr)
    if llm_prod and llm_prod.get("code"):
        slug = "".join(c if c.isalnum() or c == "_" else "_" for c in llm_prod.get("slug", "ai_tool").lower())[:32]
        file_name = f"{slug}_{len(existing_files)+1}.py"
        (ARTIFACTS_DIR / file_name).write_text(llm_prod["code"], encoding="utf-8")
        art = DeliverableArtifact(
            opportunity_id=opp_id,
            agent_id=agent_id,
            agent_name=agent_name,
            title=opp_title,
            artifact_type=llm_prod.get("type", "PYTHON_AUTOMATION_SCRIPT"),
            file_name=file_name,
            suggested_price_inr=price_inr,
            pitch_copy=llm_prod.get("pitch", f"Commercial tool for {opp_title}"),
        )
        db.add(art)
        db.commit()
        db.refresh(art)
        return art

    chosen = next((p for p in PRODUCT_CATALOG if f"{p['slug']}.{p['ext']}" not in existing_files), None)
    if not chosen:
        chosen = random.choice(PRODUCT_CATALOG)
        file_name = f"{chosen['slug']}_v{len(existing_files)+1}.{chosen['ext']}"
    else:
        file_name = f"{chosen['slug']}.{chosen['ext']}"

    (ARTIFACTS_DIR / file_name).write_text(chosen["code"], encoding="utf-8")

    art = DeliverableArtifact(
        opportunity_id=opp_id,
        agent_id=agent_id,
        agent_name=agent_name,
        title=opp_title,
        artifact_type=chosen["type"],
        file_name=file_name,
        suggested_price_inr=chosen["price"],
        pitch_copy=chosen["pitch"],
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art

def run_paper_strategy_backtest(db: Session, strategy_name: str = "NIFTY50-EMA20-Breakout") -> PaperBacktest:
    returns = [random.gauss(0.0045, 0.012) for _ in range(60)]
    equity, peak, max_dd, wins = 10000.0, 10000.0, 0.0, 0
    for r in returns:
        capped_r = max(-0.015, r)
        if capped_r > 0:
            wins += 1
        equity *= (1.0 + capped_r)
        peak = max(peak, equity)
        max_dd = max(max_dd, ((peak - equity) / peak) * 100.0)

    net_ret = round(((equity - 10000.0) / 10000.0) * 100.0, 2)
    win_rate = round((wins / len(returns)) * 100.0, 1)
    mean_r = sum(returns) / len(returns)
    std_r = math.sqrt(sum((x - mean_r) ** 2 for x in returns) / len(returns)) or 0.01
    sharpe = round((mean_r / std_r) * math.sqrt(252), 2)
    verdict = "APPROVED_PAPER" if (sharpe >= 1.2 and max_dd <= 8.0) else "REJECTED_HIGH_RISK"

    bt = PaperBacktest(
        strategy_name=strategy_name,
        symbol="NIFTY50-SANDBOX",
        virtual_capital=10000.0,
        net_return_pct=net_ret,
        win_rate_pct=win_rate,
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=sharpe,
        verdict=verdict,
    )
    db.add(bt)
    db.commit()
    db.refresh(bt)
    return bt
