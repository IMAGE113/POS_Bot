import os
import json
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv
import httpx
import aiosqlite
from google import genai

# -------------------- SETUP --------------------
load_dotenv()

# 🛠️ FastAPI ရဲ့ Startup/Shutdown အတွက် Lifespan အသစ်
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup လုပ်ငန်းစဉ်များ
    await init_db()
    asyncio.create_task(telegram_worker())
    asyncio.create_task(periodic_menu_refresh())
    await update_menu_cache()
    logging.info("✅ Server started and menu cache updated.")
    
    yield # ဒီနေရာမှာ Server က ပုံမှန်အလုပ်လုပ်နေမှာပါ
    
    logging.info("🛑 Server is shutting down.")

app = FastAPI(lifespan=lifespan)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -------------------- ENV VARIABLES --------------------
NOTION_API = os.getenv("NOTION_API")
DB_INVENTORY = os.getenv("DB_INVENTORY")
DB_ORDERS = os.getenv("DB_ORDERS")
DB_LINE_ITEMS = os.getenv("DB_LINE_ITEMS")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

required_envs = [
    ("NOTION_API", NOTION_API),
    ("DB_INVENTORY", DB_INVENTORY),
    ("DB_ORDERS", DB_ORDERS),
    ("DB_LINE_ITEMS", DB_LINE_ITEMS),
    ("GEMINI_API_KEY", GEMINI_API_KEY),
]

for name, value in required_envs:
    if not value:
        logging.warning(f"⚠️ ENV variable {name} not set. The app may not work properly.")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# 🛠️ Google GenAI Client
ai_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={'api_version': 'v1'}
)

# -------------------- GLOBALS --------------------
CURRENT_MENU_LIST = []
user_sessions = {}
telegram_queue = asyncio.Queue()
DB_FILE = "pos.db"

# -------------------- SQLITE ASYNC --------------------
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            items_json TEXT,
            payment TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """)
        await db.commit()

# -------------------- TELEGRAM --------------------
async def send_telegram(chat_id: str, text: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    await telegram_queue.put((chat_id, text))

async def telegram_worker():
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            chat_id, text = await telegram_queue.get()
            try:
                await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                  json={"chat_id": chat_id, "text": text})
            except Exception as e:
                logging.error(f"Telegram send error: {e}")
            await asyncio.sleep(1)

async def send_admin(text: str):
    if TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID:
        await send_telegram(ADMIN_CHAT_ID, text)
    else:
        logging.info(f"[ADMIN] {text}")

# -------------------- MENU & NOTION --------------------
async def notion_post_with_retry(url, json_body, retries=3):
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(retries):
            try:
                res = await client.post(url, headers=HEADERS, json=json_body)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logging.warning(f"Notion API attempt {attempt+1} failed: {e}")
                await asyncio.sleep(1 + attempt*2)
        return {}

async def update_menu_cache():
    global CURRENT_MENU_LIST
    url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    data = await notion_post_with_retry(url, {})
    results = data.get("results", [])
    new_menu = []
    for i in results:
        title = i["properties"].get("Product Name", {}).get("title", [])
        item_name = title[0]["plain_text"] if title else ""
        if item_name:
            new_menu.append(item_name)
    CURRENT_MENU_LIST = new_menu
    logging.info(f"Menu Cache Updated: {CURRENT_MENU_LIST}")

async def get_item(name: str):
    url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    data = await notion_post_with_retry(url, {})
    for i in data.get("results", []):
        title = i["properties"].get("Product Name", {}).get("title", [])
        item_name = title[0]["plain_text"] if title else ""
        if name.lower() in item_name.lower():
            stock = i["properties"].get("Stock Quantity", {}).get("number") or 0
            return {"found": True, "name": item_name, "stock": stock, "id": i["id"]}
    return {"found": False, "message": "ပစ္စည်းမတွေ့ပါဘူးရှင်။"}

# -------------------- ORDERS --------------------
async def save_order(name: str, items: str, payment: str = "COD"):
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO orders_queue (customer_name, items_json, payment, created_at) VALUES (?, ?, ?, ?)",
                (name, items, payment, datetime.now().isoformat())
            )
            await db.commit()
        return {"status": "saved", "customer": name}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def cancel_order(order_id: str, chat_id: str):
    url = f"https://api.notion.com/v1/databases/{DB_ORDERS}/query"
    data = await notion_post_with_retry(url, {
        "filter": {"property": "Order ID", "title": {"equals": order_id}}
    })
    results = data.get("results", [])
    if not results:
        return {"status": "not_found", "message": "အော်ဒါနံပါတ် ရှာမတွေ့ပါဘူးရှင်။"}
    page = results[0]
    page_id = page["id"]
    status = page["properties"].get("Status", {}).get("select", {}).get("name", "")
    
    if status == "Pending":
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"https://api.notion.com/v1/pages/{page_id}", 
                headers=HEADERS,
                json={"properties": {"Status": {"select": {"name": "Cancelled"}}}}
            )
        return {"status": "cancelled", "message": f"အော်ဒါ {order_id} ကို အောင်မြင်စွာ ပယ်ဖျက်ပေးပြီးပါပြီရှင်။"}
    
    elif status == "Processing":
        await send_admin(f"🔔 ယူဆာ {chat_id} က အော်ဒါ {order_id} (Processing) ကို ဖျက်ချင်နေပါတယ်။")
        return {"status": "processing", "message": "အော်ဒါက ပြင်ဆင်နေတဲ့ အဆင့်ရောက်နေလို့ Admin ကို အကြောင်းကြားထားပါတယ်။"}
    
    else:
        return {"status": "other", "message": f"ဒီအော်ဒါက {status} အခြေအနေ ဖြစ်နေလို့ ဖျက်ပေးလို့ မရနိုင်တော့ပါဘူးရှင်။"}

# -------------------- SYNC --------------------
async def sync_notion():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, customer_name, items_json, payment FROM orders_queue WHERE sync_status='pending'") as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return
            async with httpx.AsyncClient(timeout=10) as client:
                for r in rows:
                    oid, name, items_json, payment = r
                    order_id = f"ORD-{oid}-{datetime.now().strftime('%H%M')}"
                    try:
                        order_data = await notion_post_with_retry(
                            "https://api.notion.com/v1/pages",
                            {
                                "parent": {"database_id": DB_ORDERS},
                                "properties": {
                                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                                    "Payment Method": {"select": {"name": payment}},
                                    "Status": {"select": {"name": "Pending"}}
                                }
                            }
                        )
                        if "id" in order_data:
                            items = json.loads(items_json)
                            for item in items:
                                detail = await get_item(item.get("name", ""))
                                if detail.get("found"):
                                    await client.post(
                                        "https://api.notion.com/v1/pages",
                                        headers=HEADERS,
                                        json={
                                            "parent": {"database_id": DB_LINE_ITEMS},
                                            "properties": {
                                                "Line Item": {"title": [{"text": {"content": detail["name"]}}]},
                                                "Quantity": {"number": int(item.get("qty", 1))},
                                                "Item": {"relation": [{"id": detail["id"].replace("-", "")}]},
                                                "Orders": {"relation": [{"id": order_data["id"].replace("-", "")}]}
                                            }
                                        }
                                    )
                            await db.execute("UPDATE orders_queue SET sync_status='done' WHERE id=?", (oid,))
                            await db.commit()
                            await send_admin(f"🚀 Order synced: {order_id}")
                        await asyncio.sleep(1)
                    except Exception as e:
                        logging.error(f"Sync error for order {oid}: {e}")

# -------------------- AI SESSION --------------------
def get_system_prompt():
    menu_str = ", ".join(CURRENT_MENU_LIST) if CURRENT_MENU_LIST else "No items fetched yet"
    return f"""
You are a smart, polite, and helpful shop assistant for 'Randy's Cafe'.
- Speak naturally in Burmese as a friendly human (not like a robot). 
- Use polite particles like "ရှင်" (shin) or "နော်" (naw) where appropriate.
- Be short, helpful, and focused on assisting the customer with their order or queries.

Available menu items: [{menu_str}]

Rule: When users ask for an item in Burmese, match it with the closest available menu item in English from the list above.

Tools: get_item, save_order, cancel_order
"""

# 🛠️ ပိုစိတ်ချရစေရန် types.ChatConfig အစား Python Dictionary သက်သက်ဖြင့် ပြင်ဆင်ထားပါသည်
def get_or_create_chat(chat_id: str):
    if chat_id not in user_sessions:
        user_sessions[chat_id] = ai_client.chats.create(
            model="gemini-1.5-flash",
            config={
                "system_instruction": get_system_prompt(),
                "tools": [get_item, save_order, cancel_order],
                "temperature": 0.7
            }
        )
    return user_sessions[chat_id]

def reset_session(chat_id: str):
    if chat_id in user_sessions:
        del user_sessions[chat_id]

# -------------------- PERIODIC TASKS --------------------
async def periodic_menu_refresh(interval=300):
    while True:
        await update_menu_cache()
        await asyncio.sleep(interval)

# -------------------- WEBHOOK --------------------
@app.post("/webhook")
async def webhook(req: Request, bg: BackgroundTasks):
    data = await req.json()
    message = data.get("message", {})
    text = message.get("text")
    chat_id = message.get("chat", {}).get("id")
    if not text or not chat_id:
        return {"ok": True}

    try:
        if not CURRENT_MENU_LIST:
            await update_menu_cache()
        chat = get_or_create_chat(str(chat_id))
        response = chat.send_message(text)

        loop_count = 0
        while response.function_calls and loop_count < 5:
            loop_count += 1
            function_responses = []
            for call in response.function_calls:
                result = {"status": "error", "message": "Unknown error"}
                try:
                    args = call.args or {}
                    if call.name == "get_item":
                        result = await get_item(args.get("name", ""))
                    elif call.name == "save_order":
                        result = await save_order(
                            args.get("name", ""),
                            args.get("items", "[]"),
                            args.get("payment", "COD")
                        )
                        if result.get("status") == "saved":
                            reset_session(str(chat_id))
                            bg.add_task(sync_notion)
                    elif call.name == "cancel_order":
                        result = await cancel_order(args.get("order_id", ""), str(chat_id))
                except Exception as e:
                    logging.error(f"Function call error ({call.name}): {e}")
                    result = {"status": "error", "message": str(e)}
                
                # Function response ပို့တဲ့ ပုံစံအသစ်
                function_responses.append({
                    "function_response": {
                        "name": call.name,
                        "response": {"result": result}
                    }
                })
            
            response = chat.send_message(function_responses)

        reply = response.text or "⚠️ တောင်းပန်ပါတယ်ရှင့်၊ အခုလုပ်ဆောင်နိုင်သေးတာ မဟုတ်လို့ပါနော်။"
    except Exception as e:
        logging.error(f"AI error for chat {chat_id}: {e}")
        reply = "❌ ဆာဗာအမှားအယွင်း ရှိနေပါတယ်ရှင်၊ ခဏလေး စောင့်ပေးပါဦးနော်။"

    await send_telegram(str(chat_id), reply)
    return {"ok": True}

# -------------------- RUN --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
