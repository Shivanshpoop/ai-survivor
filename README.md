# AI SURVIVOR — Phase 1: Core Engine

## Included in Phase 1
- Central Treasury initialized at **₹5,000.00** with a protected 20% (**₹1,000.00**) Emergency Reserve.
- Double-entry immutable `LedgerEntry` table with `idempotency_key` duplicate protection.
- Agent Registry with isolated per-agent wallets, 30% single-agent concentration cap, and fund recall upon suspension.
- Real-time Survival Monitor that permanently transitions the system to `DESTROYED` if total capital reaches `₹0`.
- Strict isolation between simulated paper returns and verified real cash.
- Bearer token (`ADMIN_TOKEN`) authentication and one-click SQLite database backup.

## Windows PowerShell Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set a strong ADMIN_TOKEN
python test_phase1.py
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000` in your browser and connect with your `ADMIN_TOKEN`.
