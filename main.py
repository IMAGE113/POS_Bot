import os
import httpx
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI

# ၁။ FastAPI App Setup
app = FastAPI()

# ၂။ Environment Variables
# မင်း Render မှာ ပေးခဲ့တဲ့ NOTION_API ဆိုတဲ့ နာမည်အတိုင်း ဒီမှာ လှမ်းခေါ်ထားပါတယ်
NOTION_API = os.environ.get("NOTION_API")
DB_INVENTORY = os.environ.get("DB_INVENTORY")
DB_ORDERS = os.environ.get("DB_ORDERS")
DB_LINE_ITEMS = os.environ.get("DB_LINE_ITEMS")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.get("/")
async def root():
    return {"status": "Online", "message": "Randy's POS System is Ready!"}

async def add_line_item(client, item_name, qty, main_order_id):
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    search_res = await client.post(search_url, headers=HEADERS, json={})
    all_items = search_res.json().get("results", [])
    
    inventory_id = None
    for item in all_items:
        try:
            not_item_name = item["properties"]["Product Name"]["title"][0]["plain_text"]
            if not_item_name.lower().strip() == item_name.lower().strip():
                inventory_id = item["id"]
                break
        except:
            continue

    if inventory_id:
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {item_name}"}}]},
                "Item": {"relation": [{"id": inventory_id}]}, 
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id}]}
            }
        }
        await client.post(url, headers=HEADERS, json=payload)

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A", address: str = "N/A", payment: str = "COD"):
    async with httpx.AsyncClient() as client:
        try:
            url = "https://api.notion.com/v1/pages"
            order_id = f"ORD-{datetime.now().strftime('%d%H%M')}"
            
            # Orders DB မှာ Name, Phone, Address, Payment Method အစုံထည့်မယ်
            order_payload = {
                "parent": {"database_id": DB_ORDERS},
                "properties": {
                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                    "Phone": {"rich_text": [{"text": {"content": phone}}]},
                    "Address": {"rich_text": [{"text": {"content": address}}]},
                    "Payment Method": {"select": {"name": payment}},
                    "Status": {"select": {"name": "New"}}
                }
            }
            main_res = await client.post(url, headers=HEADERS, json=order_payload)
            main_data = main_res.json()

            if "id" not in main_data:
                return {"status": "Notion Error", "detail": main_data}

            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_data["id"]) for item in order_list]
            await asyncio.gather(*tasks)

            return {"status": "Success", "order_id": order_id}
        except Exception as e:
            return {"status": "Error", "msg": str(e)}
