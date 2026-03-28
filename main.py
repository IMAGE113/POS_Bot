import os, httpx, json, asyncio, random, string
from datetime import datetime
from fastapi import FastAPI

# Render က ဒါကို ရှာတာပါ
app = FastAPI()

# Database IDs (Hardcoded for testing)
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
    return {"status": "Online", "message": "Randy's POS System is Live!"}

async def add_line_item(client, item_name, qty, main_order_id):
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    # Screenshot အရ "Product Name" လို့ ပြင်ထားတယ်
    search_payload = {
        "filter": {"property": "Product Name", "title": {"equals": item_name}}
    }
    search_res = await client.post(search_url, headers=HEADERS, json=search_payload)
    results = search_res.json().get("results", [])
    
    if results:
        inventory_id = results[0]["id"]
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
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A"):
    async with httpx.AsyncClient() as client:
        try:
            # ၁။ အော်ဒါအသစ် ဆောက်မယ်
            url = "https://api.notion.com/v1/pages"
            order_id = f"ORD-{datetime.now().strftime('%d%H%M')}"
            order_payload = {
                "parent": {"database_id": DB_ORDERS},
                "properties": {
                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                    "Phone": {"rich_text": [{"text": {"content": phone}}]}
                }
            }
            main_res = await client.post(url, headers=HEADERS, json=order_payload)
            main_data = main_res.json()

            if "id" not in main_data:
                return {"status": "Notion Error", "detail": main_data}

            # ၂။ Line Items တွေကို တစ်ခုချင်းစီ ထည့်မယ်
            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_data["id"]) for item in order_list]
            await asyncio.gather(*tasks)

            return {"status": "Success", "order_id": order_id}
        except Exception as e:
            return {"status": "Error", "msg": str(e)}
