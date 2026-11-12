# NovaCraft Studio — Multi-Agent Business & Treasury Simulator

An experimental multi-agent orchestration engine built with **FastAPI**, **SQLAlchemy**, and **LLM APIs** that simulates autonomous opportunity discovery, capital allocation, digital product generation, and risk-gated paper backtesting.

## Features
- **Multi-Agent Swarm (pp/agents/):** Coordinates specialized agents for market research, digital tool creation, content generation, and risk management.
- **Treasury & Survival Engine (pp/services/treasury_engine.py):** Tracks virtual capital, emergency reserve guardrails, and ROI performance.
- **Interactive Storefront & Control Dashboard (static/):** Showcases generated browser tools alongside an operator telemetry dashboard.

## Quick Start
`ash
pip install -r requirements.txt
uvicorn app.main:app --reload
`
- **Storefront Demo:** http://127.0.0.1:8000/
- **Control Dashboard:** http://127.0.0.1:8000/ops-control-98765

## Disclaimer
Intended strictly for educational, architectural, and sandbox simulation purposes.
