import os
import httpx
import json
import asyncio
import random
import string
from datetime import datetime
from fastapi import FastAPI

# ၁။ FastAPI App ကို အရင်ဆောက်မယ် (Render က ဒါကို ရှာတာပါ)
app = FastAPI()

# ၂။ Database IDs & Token
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DB_INVENTORY = "d0b70b1aee10479b8a42a9d86c9936bc"
DB_ORDERS = "ad29c4830862493188d709b3920e6ac5"
DB_LINE_ITEMS = "e800442fdc454cdb8a4b9e10efdbe29c"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.get("/")
async def root():
    return {"status": "Online", "message": "Randy's POS System is Ready!"}

async def add_line_item(client, item_name, qty, main_order_id):
    # Inventory ထဲမှာ ပစ္စည်းနာမည် တူတာရှိလား အရင်ရှာမယ်
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    search_res = await client.post(search_url, headers=HEADERS, json={})
    all_items = search_res.json().get("results", [])
    
    inventory_id = None
    # စာလုံးအကြီးအသေး မရွေးဘဲ (Case-insensitive) တိုက်စစ်မယ်
    for item in all_items:
        try:
            # "Product Name" column အောက်က စာသားကို ယူတယ်
            notion_item_name = item["properties"]["Product Name"]["title"][0]["plain_text"]
            if notion_item_name.lower().strip() == item_name.lower().strip():
                inventory_id = item["id"]
                break
        except:
            continue

    if inventory_id:
        # Inventory ID တွေ့ရင် Line Item database ထဲမှာ Row ဆောက်ပြီး Relation ချိတ်မယ်
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
        return True
    return False

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A"):
    async with httpx.AsyncClient() as client:
        try:
            # ၁။ Orders Database မှာ Main Order အရင်ဆောက်မယ်
            url = "https://api.notion.com/v1/pages"
            order_id = f"ORD-{datetime.now().strftime('%d%H%M')}"
            order_payload = {
                "parent": {"database_id": DB_ORDERS},
                "properties": {
                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                    "Phone": {"rich_text": [{"text": {"content": phone}}]},
                    "Status": {"select": {"name": "New"}}
                }
            }
            main_res = await client.post(url, headers=HEADERS, json=order_payload)
            main_data = main_res.json()

            if "id" not in main_data:
                return {"status": "Notion Error", "detail": main_data}

            # ၂။ ပါလာတဲ့ Item စာရင်းတွေကို Line Items database ထဲ ပို့မယ်
            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_data["id"]) for item in order_list]
            await asyncio.gather(*tasks)

            return {"status": "Success", "order_id": order_id}
        except Exception as e:
            return {"status": "Error", "msg": str(e)}
