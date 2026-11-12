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

def _bot_creds():
    return settings.TELEGRAM_BOT_TOKEN.strip(), str(settings.TELEGRAM_CHAT_ID).strip()

async def register_telegram_commands_and_webhook():
    token, chat_id = _bot_creds()
    if not token:
        return {"ok": False, "reason": "TELEGRAM_BOT_TOKEN missing"}
    base = f"https://api.telegram.org/bot{token}"
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
            r2 = await client.post(f"{base}/setWebhook", json={"url": webhook_url, "drop_pending_updates": True})
            results["webhook"] = r2.json()
            if chat_id:
                r3 = await client.post(f"{base}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "✅ NovaCraft Menu Connected! Tap any button below.",
                    "reply_markup": MENU_KEYBOARD,
                })
                results["menu_pushed"] = r3.json()
    except Exception as e:
        results["error"] = str(e)
    return results

async def send_telegram_alert(text: str, with_menu: bool = True, target_chat_id: str = ""):
    token, default_chat = _bot_creds()
    chat_id = target_chat_id.strip() or default_chat
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if with_menu:
        payload["reply_markup"] = MENU_KEYBOARD
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json=payload)
        return True
    except Exception:
        return False

async def update_live_heartbeat(text: str):
    token, chat_id = _bot_creds()
    if not token or not chat_id:
        return
    base = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            old_id = LIVE_STATUS_STATE.get("message_id")
            if old_id:
                await client.post(f"{base}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": old_id,
                })
            r = await client.post(f"{base}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": MENU_KEYBOARD,
            })
            if r.status_code == 200:
                LIVE_STATUS_STATE["message_id"] = r.json().get("result", {}).get("message_id")
    except Exception:
        pass
