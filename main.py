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
    
    try:
        # ဘာ Filter မှ မခံဘဲ ဇယားထဲက အကုန်ဆွဲထုတ်ခြင်း
        search_res = await client.post(search_url, headers=HEADERS, json={})
        res_data = search_res.json()
        all_items = res_data.get("results", [])
        
        print(f"🔎 [DEBUG] Inventory ထဲမှာ စုစုပေါင်း ပစ္စည်း {len(all_items)} ခု တွေ့ပါတယ်။")
        
    except Exception as e:
        print(f"❌ [DEBUG] Inventory ဆွဲထုတ်ရာတွင် Error တက်ပါသည်- {e}")
        return

    inventory_id = None
    for item in all_items:
        try:
            properties = item.get("properties", {})
            
            # 💡 ဇယားထဲက တွေ့သမျှ Column နာမည်တွေကို Logs ထဲမှာ ထုတ်ပြခြင်း
            print(f"📊 [DEBUG] ဇယားထဲက Column များ- {list(properties.keys())}")
            
            product_name_prop = properties.get("Product Name", {})
            title_list = product_name_prop.get("title", [])
            
            if not title_list or len(title_list) == 0:
                print(f"⚠️ [DEBUG] 'Product Name' အကွက်ထဲမှာ Title စာသား မတွေ့ရပါ။ (Type လွဲနေနိုင်သည်)")
                continue
                
            not_item_name = title_list[0].get("plain_text", "")
            print(f"👀 [DEBUG] စစ်ဆေးနေသည်- '{not_item_name}' (မင်းရှာတာက- '{item_name}')")
            
            if not_item_name.lower().strip() == item_name.lower().strip():
                inventory_id = item["id"].replace("-", "")
                print(f"🎯 [DEBUG] '{item_name}' ကို ရှာတွေ့ပါပြီ!")
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
        res = await client.post(url, headers=HEADERS, json=payload)
        print(f"📝 [DEBUG] Line Item အသစ်ဆောက်သည့် ရလဒ် Status Code: {res.status_code}")
    else:
        print(f"❌ [DEBUG] '{item_name}' ကို Inventory ထဲမှာ ရှာမတွေ့တဲ့အတွက် Line Item မဆောက်ဖြစ်လိုက်ပါဘူး။")

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
                return {"status": "Notion Error", "detail": main_data}

            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_data["id"]) for item in order_list]
            await asyncio.gather(*tasks)

            return {"status": "Success", "order_id": order_id}
        except Exception as e:
            return {"status": "Error", "msg": str(e)}
