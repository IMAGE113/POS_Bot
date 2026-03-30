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
DB_REPORTS = os.environ.get("DB_REPORTS")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.get("/")
async def root():
    return {"status": "Online", "message": "Randy's POS System!"}

async def get_report_page_ids(client):
    daily_id = None
    monthly_id = None
    if not DB_REPORTS:
        return None, None
        
    url = f"https://api.notion.com/v1/databases/{DB_REPORTS}/query"
    try:
        res = await client.post(url, headers=HEADERS, json={})
        results = res.json().get("results", [])
        
        for page in results:
            properties = page.get("properties", {})
            for prop_name, prop_val in properties.items():
                if prop_val.get("type") == "title":
                    title_list = prop_val.get("title", [])
                    if title_list:
                        title_text = title_list[0].get("plain_text", "").strip()
                        if title_text == "Daily Reports":
                            daily_id = page["id"]
                        elif title_text == "Monthly Profit":
                            monthly_id = page["id"]
                            
        return daily_id, monthly_id
    except Exception as e:
        return None, None

async def add_line_item(client, item_name, qty, main_order_id):
    await asyncio.sleep(0.1)
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    
    try:
        search_res = await client.post(search_url, headers=HEADERS, json={})
        all_items = search_res.json().get("results", [])
    except Exception as e:
        return

    inventory_id = None
    for item in all_items:
        try:
            properties = item.get("properties", {})
            product_name_prop = properties.get("Product Name", {})
            title_list = product_name_prop.get("title", [])
            
            if not title_list:
                continue
                
            not_item_name = title_list[0].get("plain_text", "")
            
            if not_item_name.lower().strip() == item_name.lower().strip():
                inventory_id = item["id"].replace("-", "")
                break
        except Exception as e:
            continue

    if inventory_id:
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {item_name}"}}]},
                "Item": {"relation": [{"id": inventory_id}]}, 
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id.replace("-", "")}]}
            }
        }
        await client.post(url, headers=HEADERS, json=payload)

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A", address: str = "N/A", payment: str = "COD"):
    async with httpx.AsyncClient() as client:
        try:
            url = "https://api.notion.com/v1/pages"
            now = datetime.now()
            order_id = f"ORD-{now.strftime('%d%H%M')}"
            
            daily_id, monthly_id = await get_report_page_ids(client)
            
            reports_relation = []
            if daily_id:
                reports_relation.append({"id": daily_id.replace("-", "")})
            if monthly_id:
                reports_relation.append({"id": monthly_id.replace("-", "")})
            
            order_payload = {
                "parent": {"database_id": DB_ORDERS},
                "properties": {
                    "Order ID": {"title": [{"text": {"content": order_id}}]},
                    "Customer Name": {"rich_text": [{"text": {"content": name}}]},
                    "Phone": {"rich_text": [{"text": {"content": phone}}]},
                    "Address": {"rich_text": [{"text": {"content": address}}]},
                    "Payment Method": {"select": {"name": payment}},
                    # 🔴 ဒီနေရာမှာ Notion Database ထဲကအတိုင်း ကွက်တိ စာသားကိုပဲ ထည့်ပေးရပါတယ်
                    # အကယ်၍ အလုပ်မလုပ်ရင် Space ပါတဲ့ " Pending" ဆိုတာမျိုး ပြောင်းကြည့်ဖို့ လိုနိုင်ပါတယ်
                    "Status": {"select": {"name": "Pending"}}, 
                    "Reports": {"relation": reports_relation}
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
