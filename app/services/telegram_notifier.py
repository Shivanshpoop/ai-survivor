import httpx
from app.core.config import settings

LIVE_STATUS_STATE = {"message_id": None}

MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Live Status"}, {"text": "⚡ Run Cycle Now"}],
        [{"text": "▶️ Start 30s Auto"}, {"text": "⏸️ Pause Auto"}],
        [{"text": "🛒 Open Live Store"}, {"text": "💰 Revenue Report"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

async def register_telegram_commands_and_webhook():
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "reason": "TELEGRAM_BOT_TOKEN missing in Render Environment"}
    base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
    commands = [
        {"command": "start", "description": "Open Control Menu & Live Status"},
        {"command": "status", "description": "Live Capital, Revenue & Active Agents"},
        {"command": "cycle", "description": "Execute 1 Autonomous Cycle Immediately"},
        {"command": "resume", "description": "Start 30-Second Autonomous Loop"},
        {"command": "pause", "description": "Pause 30-Second Loop"},
        {"command": "store", "description": "Get NovaCraft Storefront Link"},
    ]
    results = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r1 = await client.post(f"{base}/setMyCommands", json={"commands": commands})
            results["commands"] = r1.json()
            webhook_url = f"{settings.PUBLIC_STORE_URL.rstrip('/')}/api/telegram/webhook"
            r2 = await client.post(f"{base}/setWebhook", json={"url": webhook_url})
            results["webhook"] = r2.json()
            if settings.TELEGRAM_CHAT_ID:
                r3 = await client.post(f"{base}/sendMessage", json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": "✅ NovaCraft Autonomous Bot Menu & 30-Second Live Pulse Activated!",
                    "reply_markup": MENU_KEYBOARD,
                })
                results["menu_pushed"] = r3.json()
    except Exception as e:
        results["error"] = str(e)
    return results

async def send_telegram_alert(text: str, with_menu: bool = True):
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": settings.TELEGRAM_CHAT_ID, "text": text}
    if with_menu:
        payload["reply_markup"] = MENU_KEYBOARD
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json=payload)
        return True
    except Exception:
        return False

async def update_live_heartbeat(text: str):
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            old_id = LIVE_STATUS_STATE.get("message_id")
            if old_id:
                await client.post(f"{base}/deleteMessage", json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "message_id": old_id,
                })
            r = await client.post(f"{base}/sendMessage", json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "reply_markup": MENU_KEYBOARD,
            })
            if r.status_code == 200:
                LIVE_STATUS_STATE["message_id"] = r.json().get("result", {}).get("message_id")
    except Exception:
        pass
