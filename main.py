import os
import httpx
import json
import asyncio
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from google import genai
from google.genai import types
from dotenv import load_dotenv

# --- .env ဖိုင်ကို ဖတ်ခိုင်းခြင်း ---
load_dotenv()

app = FastAPI()

# --- API Keys & IDs (.env ထဲကနေ ဆွဲယူပါသည်) ---
NOTION_API = os.environ.get("NOTION_API")
DB_INVENTORY = os.environ.get("DB_INVENTORY")
DB_ORDERS = os.environ.get("DB_ORDERS")
DB_LINE_ITEMS = os.environ.get("DB_LINE_ITEMS")
DB_REPORTS = os.environ.get("DB_REPORTS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- Gemini AI Setup ---
ai_client = genai.Client(api_key=GEMINI_API_KEY)

with open("prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# --- SQLite Database တည်ဆောက်ခြင်း ---
def init_sqlite_db():
    conn = sqlite3.connect("pos_store.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            items_json TEXT,
            payment TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_sqlite_db()

# --- Functions (Tools) for AI ---

async def get_inventory_item(item_name_or_code: str):
    async with httpx.AsyncClient() as client:
        url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
        try:
            res = await client.post(url, headers=HEADERS, json={})
            results = res.json().get("results", [])
            search_query = item_name_or_code.lower().strip()
            
            for item in results:
                props = item.get("properties", {})
                title_list = props.get("Product Name", {}).get("title", [])
                p_name = title_list[0].get("plain_text", "").lower().strip() if title_list else ""
                
                code_list = props.get("Item Code", {}).get("rich_text", [])
                p_code = code_list[0].get("plain_text", "").lower().strip() if code_list else ""
                
                stock = props.get("Stock", {}).get("number", 0) or 0
                
                if search_query == p_name or search_query == p_code:
                    return {
                        "found": True, 
                        "name": p_name.capitalize(), 
                        "code": p_code.upper(), 
                        "stock": stock, 
                        "id": item["id"]
                    }
            return {"found": False}
        except Exception:
            return {"found": False}


async def process_sync_to_notion():
    """SQLite ထဲက ပို့ရန်ကျန်နေသော အော်ဒါများကို Notion ဆီ ပို့ပေးသည်"""
    conn = sqlite3.connect("pos_store.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, customer_name, items_json, payment FROM orders_queue WHERE sync_status = 'pending'")
    pending_orders = cursor.fetchall()
    
    if not pending_orders:
        conn.close()
        return

    async with httpx.AsyncClient() as client:
        url = "https://api.notion.com/v1/pages"
        
        for order in pending_orders:
            db_id, customer_name, items_json, payment = order
            now = datetime.now()
            order_id = f"ORD-{now.strftime('%d%H%M')}-{db_id}"
            
            try:
                # ၁။ Order ဆောက်မယ်
                order_payload = {
                    "parent": {"database_id": DB_ORDERS},
                    "properties": {
                        "Order ID": {"title": [{"text": {"content": order_id}}]},
                        "Customer Name": {"rich_text": [{"text": {"content": customer_name}}]},
                        "Payment Method": {"select": {"name": payment}},
                        "Status": {"select": {"name": "Pending"}}
                    }
                }
                
                main_res = await client.post(url, headers=HEADERS, json=order_payload)
                main_data = main_res.json()

                # ၂။ Line Items ဆောက်မယ်
                if "id" in main_data:
                    order_list = json.loads(items_json)
                    for item in order_list:
                        item_details = await get_inventory_item(item['name'])
                        if item_details["found"]:
                            line_payload = {
                                "parent": {"database_id": DB_LINE_ITEMS},
                                "properties": {
                                    "Line Item": {"title": [{"text": {"content": f"Sale: {item_details['name']}"}}]},
                                    "Item": {"relation": [{"id": item_details["id"].replace("-", "")}]}, 
                                    "Quantity": {"number": int(item['qty'])},
                                    "Orders": {"relation": [{"id": main_data["id"].replace("-", "")}]}
                                }
                            }
                            await client.post(url, headers=HEADERS, json=line_payload)
                    
                    # ပို့ပြီးရင် status ကို completed လုပ်မယ်
                    cursor.execute("UPDATE orders_queue SET sync_status = 'completed' WHERE id = ?", (db_id,))
                    conn.commit()
                    print(f"✔️ Synced Order {order_id} to Notion!")
                    await asyncio.sleep(1) # Rate limit အတွက်
                    
            except Exception as e:
                print(f"❌ Sync Error for ID {db_id}: {e}")
                
    conn.close()


async def create_final_order(customer_name: str, items_json: str, payment: str = "COD"):
    """အော်ဒါကို SQLite ထဲ အရင် သိမ်းလိုက်ပါသည်"""
    try:
        conn = sqlite3.connect("pos_store.db")
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO orders_queue (customer_name, items_json, payment, created_at) VALUES (?, ?, ?, ?)",
            (customer_name, items_json, payment, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": "Order noted locally!", "customer": customer_name}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


# --- Webhook Endpoint for Telegram ---

@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    update = await request.json()
    
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        user_text = update["message"].get("text", "")
        
        response = ai_client.models.generate_content(
            model='gemini-3-flash',
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[get_inventory_item, create_final_order],
                temperature=0.7,
            ),
        )
        
        if response.function_calls:
            for call in response.function_calls:
                if call.name == "get_inventory_item":
                    args = call.args
                    await get_inventory_item(args["item_name_or_code"])
                    
                elif call.name == "create_final_order":
                    args = call.args
                    result = await create_final_order(args["customer_name"], args["items_json"], args.get("payment", "COD"))
                    
                    if result["status"] == "success":
                        background_tasks.add_task(process_sync_to_notion)
        
        bot_reply = response.text
        
        # Telegram ဆီ စာပြန်ပို့သည့် အပိုင်း
        if bot_reply and TELEGRAM_BOT_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={
                    "chat_id": chat_id,
                    "text": bot_reply
                })
        
    return {"status": "ok"}
