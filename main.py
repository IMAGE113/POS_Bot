import os
import httpx
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI

app = FastAPI()

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
    return {"status": "Online", "message": "Randy's POS System is Fully Optimized!"}

async def add_line_item(client, item_name, qty, main_order_id):
    await asyncio.sleep(0.1)
    
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    
    all_items = []
    has_more = True
    start_cursor = None
    
    while has_more:
        query_payload = {}
        if start_cursor:
            query_payload["start_cursor"] = start_cursor
            
        search_res = await client.post(search_url, headers=HEADERS, json=query_payload)
        res_data = search_res.json()
        all_items.extend(res_data.get("results", []))
        
        has_more = res_data.get("has_more", False)
        start_cursor = res_data.get("next_cursor", None)

    inventory_id = None
    for item in all_items:
        try:
            properties = item.get("properties", {})
            product_name_prop = properties.get("Product Name", {})
            
            if not product_name_prop:
                continue
                
            title_list = product_name_prop.get("title", [])
            if not title_list or len(title_list) == 0:
                continue
                
            not_item_name = title_list[0].get("plain_text", "")
            
            if not_item_name.lower().strip() == item_name.lower().strip():
                # ID ထဲက မျဉ်းစောင်းများကို ဖြုတ်ခြင်း
                inventory_id = item["id"].replace("-", "")
                break
        except Exception as e:
            continue

    if inventory_id:
        url = "https://api.notion.com/v1/pages"
        
        clean_main_order_id = main_order_id.replace("-", "")
        
        # Notion API အတွက် အတိကျဆုံး Structure ဖြင့် ပြင်ဆင်ခြင်း
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {
                    "title": [
                        {"text": {"content": f"Sale: {item_name}"}}
                    ]
                },
                "Item": {
                    "relation": [
                        {"id": inventory_id}
                    ]
                }, 
                "Quantity": {
                    "number": int(qty)
                },
                "Orders": {
                    "relation": [
                        {"id": clean_main_order_id}
                    ]
                }
            }
        }
        
        # API ရဲ့ တုံ့ပြန်မှုကို စောင့်ကြည့်ရန်
        res = await client.post(url, headers=HEADERS, json=payload)
        print(f"📡 [DEBUG] Notion Create Page Status: {res.status_code}")
        if res.status_code != 200:
            print(f"📡 [DEBUG] Notion Error Detail: {res.text}")
    else:
        print(f"❌ [DEBUG] '{item_name}' ကို Inventory ထဲမှာ ရှာမတွေ့ပါ။")

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A", address: str = "N/A", payment: str = "COD"):
    async with httpx.AsyncClient() as client:
        try:
            url = "https://api.notion.com/v1/pages"
            order_id = f"ORD-{datetime.now().strftime('%d%H%M')}"
            
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
                print(f"❌ [DEBUG] Main Order ဆောက်တာ မအောင်မြင်ပါ- {main_data}")
                return {"status": "Notion Error", "detail": main_data}

            print(f"🎉 [DEBUG] Main Order အောင်မြင်စွာ ဆောက်ပြီးပါပြီ။ ID: {main_data['id']}")

            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_data["id"]) for item in order_list]
            await asyncio.gather(*tasks)

            return {"status": "Success", "order_id": order_id}
        except Exception as e:
            print(f"❌ [DEBUG] Checkout တစ်ခုလုံးမှာ Error တက်သွားပါတယ်- {e}")
            return {"status": "Error", "msg": str(e)}
