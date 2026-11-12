import asyncio
import os
import httpx
from playwright.async_api import async_playwright

CLOUD_URL = "https://ai-survivor.onrender.com"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-to-a-strong-secret-token-98765")
HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

async def run_local_worker():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./browser_profile",
            headless=False,
            slow_mo=350,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        print("NovaCraft Local Human-Like Browser Worker ONLINE. Polling Cloud Brain...")

        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(f"{CLOUD_URL}/api/worker/tasks", headers=HEADERS)
                    if resp.status_code == 200:
                        tasks = resp.json().get("tasks", [])
                        for t in tasks:
                            print(f"Executing Task [{t['id']}]: {t['task_type']} -> {t['subject']}")
                            if t["target_url"]:
                                await page.goto(t["target_url"], wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)

                            os.makedirs("worker_outbox", exist_ok=True)
                            out_file = f"worker_outbox/{t['id']}_{t['task_type']}.txt"
                            with open(out_file, "w", encoding="utf-8") as f:
                                f.write(f"SUBJECT: {t['subject']}\nURL: {t['target_url']}\n\n{t['payload_text']}")

                            await client.post(
                                f"{CLOUD_URL}/api/worker/tasks/{t['id']}/complete",
                                headers=HEADERS,
                                json={"status": "COMPLETED", "result_note": f"Prepared & queued in {out_file}"},
                            )
            except Exception as e:
                print("Worker polling note:", e)
            await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(run_local_worker())
