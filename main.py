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
DB_REPORTS = os.environ.get("DB_REPORTS") # 👈 Reports Database ID ထည့်ရန်

HEADERS = {
    "Authorization": f"Bearer {NOTION_API}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.get("/")
async def root():
    return {"status": "Online", "message": "Randy's POS System is fully automated!"}

# Reports DB ထဲက Daily နဲ့ Monthly Page တွေကို နာမည်အတိုင်း ရှာတဲ့ function
async def get_report_page_ids(client):
    daily_id = None
    monthly_id = None
    
    if not DB_REPORTS:
        print("⚠️ [DEBUG] DB_REPORTS ရဲ့ ID ကို Render မှာ မထည့်ရသေးပါ။")
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
                        
                        # အမည်တူရင် ID ကို ဖြတ်ယူမယ်
                        if title_text == "Daily Reports":
                            daily_id = page["id"]
                        elif title_text == "Monthly Profit":
                            monthly_id = page["id"]
                            
        return daily_id, monthly_id
    except Exception as e:
        print(f"❌ [DEBUG] Reports ရှာဖွေရာတွင် Error တက်ပါသည်- {e}")
        return None, None

async def add_line_item(client, item_name, qty, main_order_id):
    await asyncio.sleep(0.1)
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    
    try:
        search_res = await client.post(search_url, headers=HEADERS, json={})
        all_items = search_res.json().get("results", [])
        print(f"🔎 [DEBUG] Inventory ထဲမှာ စုစုပေါင်း ပစ္စည်း {len(all_items)} ခု တွေ့ပါတယ်။")
        
    except Exception as e:
        print(f"❌ [DEBUG] Inventory ဆွဲထုတ်ရာတွင် Error တက်ပါသည်- {e}")
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
        res = await client.post(url, headers=HEADERS, json=payload)
        print(f"📝 [DEBUG] Line Item အသစ်ဆောက်သည့် ရလဒ်- {res.status_code}")
    else:
        print(f"❌ [DEBUG] '{item_name}' ကို Inventory ထဲမှာ ရှာမတွေ့ပါ။")

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A", address: str = "N/A", payment: str = "COD"):
    async with httpx.AsyncClient() as client:
        try:
            url = "https://api.notion.com/v1/pages"
            order_id = f"ORD-{datetime.now().strftime('%d%H%M')}"
            
            # Reports DB ထဲက page ID တွေကို အရင် သွားရှာခိုင်းမယ်
            daily_id, monthly_id = await get_report_page_ids(client)
            print(f"🔗 [DEBUG] Auto Reports ရှာဖွေတွေ့ရှိမှု - Daily: {daily_id}, Monthly: {monthly_id}")
            
            # Relation ထဲကို ထည့်ဖို့ list ဆောက်မယ်
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
                    # ၁။ Dashboard မှာ ပေါ်အောင် Pending လို့ ပြောင်းထားပါတယ်
                    "Status": {"select": {"name": "Pending"}},
                    # ၂။ Reports (၂) ခုလုံးနဲ့ အော်တို ချိတ်ပေးသွားမှာပါ 
                    "Reports": {"relation": reports_relation}
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
            return {"status": "Error", "msg": str(e)}
