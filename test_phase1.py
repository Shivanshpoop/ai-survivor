import os
os.environ["DATABASE_URL"] = "sqlite:///./test_phase1.db"
os.environ["ADMIN_TOKEN"] = "phase1-test-token"

from fastapi.testclient import TestClient
from app.main import app

def test_phase_1():
    if os.path.exists("test_phase1.db"):
        os.remove("test_phase1.db")

    with TestClient(app) as client:
        auth = {"Authorization": "Bearer phase1-test-token"}

        # 1. Security check: unauthenticated requests blocked
        assert client.get("/api/state").status_code in (401, 403)

        # 2. Genesis check: INR 5,000 total, INR 1,000 reserve, INR 4,000 spendable
        state = client.get("/api/state", headers=auth).json()
        assert state["treasury"]["total_capital"] == 5000.0
        assert state["treasury"]["emergency_reserve"] == 1000.0
        assert state["treasury"]["spendable_treasury"] == 4000.0
        assert state["treasury"]["survival_status"] == "ALIVE"

        # 3. Create agent with INR 500 budget
        res_ag = client.post("/api/agents", headers=auth, json={
            "name": "Market Research Agent",
            "role": "RESEARCHER",
            "mission": "Find profitable micro-SaaS niches",
            "initial_budget": 500.0
        })
        assert res_ag.status_code == 200
        ag_id = res_ag.json()["id"]

        # 4. Verify budget isolation & single-agent cap (30% of 5000 = 1500 max)
        res_over_cap = client.post(f"/api/agents/{ag_id}/allocate", headers=auth, json={
            "agent_id": ag_id,
            "amount": 1200.0,
            "reason": "Exceeds 30% single agent cap"
        })
        assert res_over_cap.status_code == 400

        # 5. Record valid expense of INR 100
        res_exp = client.post("/api/ledger/expense", headers=auth, json={
            "agent_id": ag_id,
            "amount": 100.0,
            "description": "Domain & market dataset query"
        })
        assert res_exp.status_code == 200
        assert res_exp.json()["total_capital_after"] == 4900.0

        # 6. Prevent agent overspending its own INR 400 remaining balance
        res_overspend = client.post("/api/ledger/expense", headers=auth, json={
            "agent_id": ag_id,
            "amount": 450.0,
            "description": "Unauthorized overspend"
        })
        assert res_overspend.status_code == 400

        # 7. Verify paper return does NOT inflate real cash
        res_rev = client.post("/api/ledger/revenue", headers=auth, json={
            "agent_id": ag_id,
            "amount": 300.0,
            "description": "Paper simulation profit"
        })
        assert res_rev.status_code == 200
        assert res_rev.json()["is_simulated"] is True
        assert res_rev.json()["total_capital_after"] == 4900.0

        # 8. Suspend agent & verify unspent INR 400 returns to Central Treasury
        res_susp = client.post(f"/api/agents/{ag_id}/suspend", headers=auth)
        assert res_susp.status_code == 200
        final_state = client.get("/api/state", headers=auth).json()
        assert final_state["treasury"]["treasury_balance"] == 4900.0
        assert final_state["treasury"]["agent_held_balance"] == 0.0

    if os.path.exists("test_phase1.db"):
        os.remove("test_phase1.db")
    print("PHASE 1 VERIFICATION SUITE PASSED 100%!")

if __name__ == "__main__":
    test_phase_1()
