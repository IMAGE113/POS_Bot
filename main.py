import os, httpx, json, asyncio, random, string
from datetime import datetime
from fastapi import FastAPI

app = FastAPI()

# Config
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DB_ORDERS = os.environ.get("DB_ID_2")      # Orders Database
DB_LINE_ITEMS = os.environ.get("DB_ID_3")  # Line Items Database
DB_INVENTORY = os.environ.get("DB_ID_1")   # Inventory Database

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ၁။ Unique Order ID ထုတ်ပေးတဲ့ Function
def generate_order_id():
    now = datetime.now().strftime("%d%H%M") # နေ့ရက်နဲ့ အချိန်
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"ORD-{now}-{suffix}"

# ၂။ Orders DB ထဲမှာ Main Order အရင်ဆောက်မယ်
async def create_main_order(client, customer_data):
    url = "https://api.notion.com/v1/pages"
    order_id = generate_order_id()
    
    payload = {
        "parent": {"database_id": DB_ORDERS},
        "properties": {
            "Order ID": {"title": [{"text": {"content": order_id}}]},
            "Status": {"select": {"name": "New"}},
            "Customer Name": {"rich_text": [{"text": {"content": customer_data.get("name", "Unknown")}}]},
            "Phone": {"phone_number": customer_data.get("phone", "N/A")}
        }
    }
    res = await client.post(url, headers=HEADERS, json=payload)
    return res.json().get("id"), order_id

# ၃။ ပစ္စည်းတစ်ခုချင်းစီကို Line Items ထဲသွင်းပြီး Main Order နဲ့ ချိတ်မယ်
async def add_line_item(client, name, qty, main_order_id):
    # Inventory မှာ Item ID ရှာမယ်
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    search_payload = {"filter": {"property": "Product Name", "title": {"equals": name}}}
    search_res = await client.post(search_url, headers=HEADERS, json=search_payload)
    results = search_res.json().get("results", [])
    
    if results:
        item_id = results[0]["id"]
        # Line Item ဆောက်မယ်
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id}]} # ဒီမှာ ချိတ်လိုက်တာ!
            }
        }
        await client.post(url, headers=HEADERS, json=payload)

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A"):
    async with httpx.AsyncClient() as client:
        # Step 1: Main Order အရင်ဆောက်
        main_id, display_id = await create_main_order(client, {"name": name, "phone": phone})
        
        # Step 2: ပစ္စည်းတွေကို Line Items ထဲ တစ်ပြိုင်တည်းသွင်း
        order_list = json.loads(items_json)
        tasks = [add_line_item(client, item['name'], item['qty'], main_id) for item in order_list]
        await asyncio.gather(*tasks)
        
        return {"status": "Success", "order_id": display_id, "items_count": len(tasks)}
