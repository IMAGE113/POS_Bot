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
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

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

async def send_noti_to_admin(message_text: str):
    """Admin ဆီသို့ Telegram မက်ဆေ့ခ်ျ လှမ်းပို့ပေးသည်"""
    if TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID:
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            try:
                await client.post(telegram_url, json={
                    "chat_id": ADMIN_CHAT_ID,
                    "text": message_text
                })
                print("✔️ Notification sent to Admin!")
            except Exception as e:
                print(f"❌ Failed to send admin noti: {e}")

async def get_inventory_item(item_name_or_code: str):
    """Notion DB ထဲမှာ ပစ္စည်းအမည် သို့မဟုတ် Code နဲ့ ရှာဖွေပြီး Stock စစ်ပေးသည်"""
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
                    
                    # Admin ဆီ Noti လှမ်းပို့ခြင်း
                    await send_noti_to_admin(f"🚀 [Prepaid] အော်ဒါအသစ် Notion သို့ ရောက်ရှိသွားပါပြီ!\nOrder ID: {order_id}\nCustomer: {customer_name}")
                    
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

async def cancel_order(order_id: str):
    """Notion DB ထဲမှာ Order ID ကို ရှာပြီး Pending ဖြစ်မှသာ Status ကို Cancelled ဟု ပြောင်းပေးသည်"""
    async with httpx.AsyncClient() as client:
        query_url = f"https://api.notion.com/v1/databases/{DB_ORDERS}/query"
        filter_payload = {
            "filter": {
                "property": "Order ID",
                "title": {
                    "equals": order_id
                }
            }
        }
        
        try:
            res = await client.post(query_url, headers=HEADERS, json=filter_payload)
            results = res.json().get("results", [])
            
            if not results:
                return {"status": "not_found", "message": "Order ID ရှာမတွေ့ပါ။"}
                
            page_id = results[0]["id"]
            props = results[0]["properties"]
            
            # Status က Pending ဟုတ်မဟုတ် စစ်မယ်
            current_status = props.get("Status", {}).get("select", {}).get("name", "")
            
            if current_status != "Pending":
                return {
                    "status": "not_allowed", 
                    "message": f"လက်ရှိ Order မှာ Status သည် '{current_status}' ဖြစ်နေသဖြင့် Bot မှ ပယ်ဖျက်၍ မရနိုင်ပါ။ Admin ကို တိုက်ရိုက် ဆက်သွယ်ပေးပါ။"
                }
            
            # Pending ဖြစ်နေရင် Cancelled လို့ Update လုပ်မယ်
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            update_payload = {
                "properties": {
                    "Status": {"select": {"name": "Cancelled"}}
                }
            }
            
            update_res = await client.patch(update_url, headers=HEADERS, json=update_payload)
            
            if update_res.status_code == 200:
                # Admin ထံ Noti ပို့ခြင်း
                await send_noti_to_admin(f"⚠️ သတိပေးချက်: Customer မှ Order ID: {order_id} ကို Cancel လိုက်ပါပြီ။")
                return {"status": "success", "message": f"Order {order_id} ကို အောင်မြင်စွာ ပယ်ဖျက်ပြီးပါပြီ။"}
            else:
                return {"status": "error", "message": "Notion တွင် ပြင်ဆင်ရန် ခေတ္တ အဆင်မပြေဖြစ်နေပါသည်။"}
                
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
                tools=[get_inventory_item, create_final_order, cancel_order], 
                temperature=0.7,
            ),
        )
        
        # AI က Function ခေါ်ခိုင်းရင်
        if response.function_calls:
            for call in response.function_calls:
                if call.name == "get_inventory_item":
                    args = call.args
                    await get_inventory_item(args["item_name_or_code"])
                    
                elif call.name == "create_final_order":
                    args = call.args
                    result = await create_final_order(args["customer_name"], args["items_json"], args.get("payment", "COD"))
                    
                    # အော်ဒါသိမ်းတာ အောင်မြင်ရင်
                    if result["status"] == "success":
                        # Prepaid ဆိုရင် Notion ဆီ လှမ်းပို့မယ်
                        if args.get("payment", "COD") == "Prepaid":
                            background_tasks.add_task(process_sync_to_notion)
                        
                elif call.name == "cancel_order":
                    args = call.args
                    await cancel_order(args["order_id"])
        
        bot_reply = response.text
        
        # --- COD အတွက် Admin ဆီ တိုက်ရိုက်လှမ်းပို့ခြင်း ---
        if bot_reply and "Admin ဆီ ပို့ပေးထားပါတယ်" in bot_reply:
            await send_noti_to_admin(f"📝 [COD မှာယူမှု အသစ်]\n{user_text}")
        
        # Telegram ဆီ စာပြန်ပို့သည့် အပိုင်း
        if bot_reply and TELEGRAM_BOT_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(telegram_url, json={
                    "chat_id": chat_id,
                    "text": bot_reply
                })
        
    return {"status": "ok"}
