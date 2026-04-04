import os
import json
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from difflib import get_close_matches

from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv
import httpx
import aiosqlite

from google import genai
from google.genai import types

# -------------------- LOAD ENV --------------------
load_dotenv()

NOTION_API = os.getenv("NOTION_API")
DB_INVENTORY = os.getenv("DB_INVENTORY")
DB_ORDERS = os.getenv("DB_ORDERS")
DB_LINE_ITEMS = os.getenv("DB_LINE_ITEMS")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def extract_notion_id(url_or_id: str) -> str:
    if not url_or_id:
        return ""
    clean_id = url_or_id.split("/")[-1].split("?")[0]
    return clean_id.replace("-", "")

NOTION_DB_INVENTORY = extract_notion_id(DB_INVENTORY)
NOTION_DB_ORDERS = extract_notion_id(DB_ORDERS)
NOTION_DB_LINE_ITEMS = extract_notion_id(DB_LINE_ITEMS)

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# -------------------- GLOBALS --------------------
DB_FILE = "pos.db"
telegram_queue = asyncio.Queue(maxsize=500)
CURRENT_MENU = []
MENU_CACHE = {}
user_sessions = {}

# -------------------- AI --------------------
ai_client = genai.Client(api_key=GEMINI_API_KEY)

def system_prompt():
    menu_str = ", ".join(CURRENT_MENU) if CURRENT_MENU else "No menu yet"
    return f"""
You are a friendly cafe assistant named 'Randy's Cafe' (Burmese speaking).
Be natural, short, and helpful. Use polite particles like "ရှင်" or "နော်".

Available Menu Items: [{menu_str}]

Critical Rules:
1. When a user asks for an item in Burmese, you MUST identify which English item from the menu they want (use your hardcoded Burmese->English mapping).
2. Call the `get_item` tool with the EXACT English name from the menu.
3. If the user asks for something not related to the menu, politely explain that we don't have it.
"""

# -------------------- MENU & ITEMS --------------------
Burmese_to_English = {
    "ကော်ဖီအေး": "Iced Coffee",
    "ကော်လာ": "Cola",
    # ဒီမှာ ခင်ဗျားရဲ့ ဆိုင် Menu စာရင်း အပြည့်အစုံကို ဆက်ထည့်ပေးပါဗျာ
}

async def get_item(name: str):
    name = Burmese_to_English.get(name, name)
    name_lower = name.lower()
    
    # ၁။ Direct match
    if name_lower in MENU_CACHE:
        item = MENU_CACHE[name_lower]
        return {
            "found": True,
            "name": item["name"],
            "id": item["id"],
            "stock": item["stock"],
            "message": f"{item['name']} က stock {item['stock']} လက်ကျန်ရှိပါတယ်ရှင်"
        }

    # ၂။ အနီးစပ်ဆုံး ရှာဖွေခြင်း
    menu_keys = list(MENU_CACHE.keys())
    matches = get_close_matches(name_lower, menu_keys, n=1, cutoff=0.7)
    if matches:
        matched_key = matches[0]
        item = MENU_CACHE[matched_key]
        return {
            "found": True,
            "name": item["name"],
            "id": item["id"],
            "stock": item["stock"],
            "message": f"{item['name']} က stock {item['stock']} လက်ကျန်ရှိပါတယ်ရှင်"
        }

    return {"found": False, "message": f"မတွေ့ပါဘူးရှင်: {name}"}

async def refresh_menu():
    global CURRENT_MENU, MENU_CACHE
    if not NOTION_DB_INVENTORY:
        logging.error("❌ DB_INVENTORY not set!")
        return

    url = f"https://api.notion.com/v1/databases/{NOTION_DB_INVENTORY}/query"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.post(url, headers=HEADERS)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            logging.error(f"Failed to fetch menu from Notion: {e}")
            return

    new_menu = []
    new_cache = {}
    for item in data.get("results", []):
        props = item["properties"]
        name_prop = props.get("Product Name", {}).get("title", [])
        name = name_prop[0]["plain_text"] if name_prop else ""
        stock = props.get("Stock Quantity", {}).get("number", 0)
        if name:
            new_menu.append(name)
            new_cache[name.lower()] = {"id": item["id"], "name": name, "stock": stock}

    CURRENT_MENU = new_menu
    MENU_CACHE = new_cache
    logging.info(f"Menu loaded: {len(CURRENT_MENU)} items")

# -------------------- DATABASE --------------------
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
async def telegram_worker():
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            chat_id, text = await telegram_queue.get()
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text}
                )
            except Exception as e:
                logging.error(f"Telegram error: {e}")
            await asyncio.sleep(0.5)

async def send(chat_id: str, text: str):
    if TELEGRAM_BOT_TOKEN:
        await telegram_queue.put((chat_id, text))

async def send_admin(text: str):
    if ADMIN_CHAT_ID:
        await send(ADMIN_CHAT_ID, text)

# -------------------- ORDERS --------------------
async def save_order(name: str, items: str, payment: str = "COD"):
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO orders_queue (customer_name, items_json, payment, created_at) VALUES (?, ?, ?, ?)",
                (name, items, payment, datetime.now().isoformat())
            )
            await db.commit()
        return {"status": "saved"}
    except Exception as e:
        logging.error(f"Save order error: {e}")
        return {"status": "error", "message": str(e)}

async def cancel_order(order_id: str):
    await send_admin(f"Cancel request: {order_id}")
    return {"status": "requested"}

# -------------------- AI SESSION --------------------
def get_chat(chat_id: str):
    if chat_id not in user_sessions:
        # ChatGPT ရဲ့ အကြံပေးချက်အတိုင်း fully-typed types.Tool object တွေ သုံးထားပါတယ်
        tools_definition = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_item",
                        description="Check the menu item and its stock quantity.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "name": types.Schema(type="STRING", description="The exact English name of the item from the menu.")
                            },
                            required=["name"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="save_order",
                        description="Save the customer's order to the database.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "name": types.Schema(type="STRING", description="Customer name."),
                                "items": types.Schema(type="STRING", description="JSON string of items ordered (e.g., '[{\"name\": \"Cola\", \"qty\": 1}]')."),
                                "payment": types.Schema(type="STRING", description="Payment method, defaults to 'COD'.")
                            },
                            required=["name", "items"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="cancel_order",
                        description="Request to cancel an existing order.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "order_id": types.Schema(type="STRING", description="The ID of the order to cancel (e.g., 'ORD-1-1200').")
                            },
                            required=["order_id"]
                        )
                    )
                ]
            )
        ]

        user_sessions[chat_id] = ai_client.chats.create(
            model="gemini-1.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt(),
                tools=tools_definition,
                temperature=0.7
            )
        )
    return user_sessions[chat_id]

def reset_chat(chat_id: str):
    user_sessions.pop(chat_id, None)

# -------------------- SYNC WITH NOTION --------------------
async def notion_post(url, payload, retries=3):
    async with httpx.AsyncClient(timeout=15) as client:
        for i in range(retries):
            try:
                res = await client.post(url, headers=HEADERS, json=payload)
                res.raise_for_status()
                return res.json()
            except Exception as e:
                logging.warning(f"Notion API retry {i+1}: {e}")
                await asyncio.sleep(2 ** i)
    return {}

async def sync_orders():
    if not NOTION_DB_ORDERS:
        logging.error("❌ DB_ORDERS not set!")
        return

    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, customer_name, items_json, payment FROM orders_queue WHERE sync_status='pending'") as cur:
            rows = await cur.fetchall()

    for oid, name, items_json, payment in rows:
        order_id = f"ORD-{oid}-{datetime.now().strftime('%H%M')}"
        order_data = await notion_post(
            "https://api.notion.com/v1/pages",
            {
                "parent": {"database_id": NOTION_DB_ORDERS},
                "properties": {
                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                    "Payment Method": {"select": {"name": payment}},
                    "Status": {"select": {"name": "Pending"}}
                }
            }
        )

        if "id" not in order_data:
            logging.error(f"❌ Failed to sync order {order_id}")
            continue

        try:
            items = json.loads(items_json)
            for item in items:
                item_name = item.get("name", "")
                qty = int(item.get("qty", 1))
                
                eng_name = Burmese_to_English.get(item_name, item_name)
                item_detail = MENU_CACHE.get(eng_name.lower())

                if item_detail and NOTION_DB_LINE_ITEMS:
                    await notion_post(
                        "https://api.notion.com/v1/pages",
                        {
                            "parent": {"database_id": NOTION_DB_LINE_ITEMS},
                            "properties": {
                                "Line Item": {"title": [{"text": {"content": item_detail["name"]}}]},
                                "Quantity": {"number": qty},
                                # ChatGPT အကြံပေးထားပေမဲ့ Notion API အရ Dash မဖြုတ်ဘဲ မူရင်း Format အတိုင်း ထားရပါမယ်
                                "Item": {"relation": [{"id": item_detail["id"]}]},
                                "Orders": {"relation": [{"id": order_data["id"]}]}
                            }
                        }
                    )
        except Exception as e:
            logging.error(f"Failed to sync line items for {order_id}: {e}")

        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE orders_queue SET sync_status='done' WHERE id=?", (oid,))
            await db.commit()

        await send_admin(f"✅ Synced {order_id}")

# -------------------- AI HANDLE --------------------
async def handle_ai(chat_id: str, text: str, bg: BackgroundTasks):
    chat = get_chat(chat_id)
    response = await asyncio.to_thread(chat.send_message, text)

    loop = 0
    while response.function_calls and loop < 5:
        loop += 1
        results = []
        for call in response.function_calls:
            args = call.args or {}
            result = {"status": "error", "message": "unknown"}
            try:
                if call.name == "get_item":
                    result = await get_item(args.get("name", ""))
                elif call.name == "save_order":
                    result = await save_order(args.get("name", ""), args.get("items", "[]"), args.get("payment", "COD"))
                    reset_chat(chat_id)
                    bg.add_task(sync_orders)
                elif call.name == "cancel_order":
                    result = await cancel_order(args.get("order_id", ""))
            except Exception as e:
                logging.error(f"Function {call.name} error: {e}")
                result = {"status": "error", "message": str(e)}

            # SDK အသစ်တွင် types.Part သုံး၍ Function Response ပြန်ခြင်း
            results.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name,
                        response={"result": result}
                    )
                )
            )

        response = await asyncio.to_thread(chat.send_message, results)

    return response.text or "တောင်းပန်ပါတယ်ရှင်၊ မရနိုင်သေးပါဘူးနော်။"

# -------------------- FASTAPI --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await refresh_menu()
    asyncio.create_task(telegram_worker())

    async def loop_tasks():
        while True:
            await asyncio.sleep(300)
            await refresh_menu()
            await sync_orders()

    asyncio.create_task(loop_tasks())
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(req: Request, bg: BackgroundTasks):
    data = await req.json()
    msg = data.get("message", {})
    text = msg.get("text")
    chat_id = str(msg.get("chat", {}).get("id"))

    if not text:
        return {"ok": True}

    try:
        reply = await handle_ai(chat_id, text, bg)
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        reply = "ခဏလေး စောင့်ပေးပါဦးနော်၊ စနစ်ထဲမှာ အမှားတစ်ခု ရှိနေလို့ပါရှင်။"

    await send(chat_id, reply)
    return {"ok": True}

# -------------------- RUN --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
