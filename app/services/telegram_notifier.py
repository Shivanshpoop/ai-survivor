import httpx
from app.core.config import settings

async def send_telegram_alert(text: str):
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text})
        return True
    except Exception:
        return False
