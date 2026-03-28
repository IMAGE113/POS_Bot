import os, httpx, json, asyncio, random, string
from datetime import datetime
from fastapi import FastAPI

app = FastAPI()

# မင်းပေးထားတဲ့ ID တွေအတိုင်း Environment Variables ထဲမှာ ထည့်ထားမယ်
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DB_INVENTORY = "d0b70b1aee10479b8a42a9d86c9936bc"  # DB 1
DB_ORDERS = "ad29c4830862493188d709b3920e6ac5"     # DB 2
DB_LINE_ITEMS = "e800442fdc454cdb8a4b9e10efdbe29c"  # DB 3

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def generate_order_id():
    now = datetime.now().strftime("%d%H%M")
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"ORD-{now}-{suffix}"

async def create_main_order(client, customer_data):
    url = "https://api.notion.com/v1/pages"
    order_id = generate_order_id()
    
    payload = {
        "parent": {"database_id": DB_ORDERS},
        "properties": {
            "Order ID": {"title": [{"text": {"content": order_id}}]},
            "Status": {"select": {"name": "New"}}
        }
    }

    # Phone က Text Type ဖြစ်တဲ့အတွက် rich_text အနေနဲ့ ပို့ရမယ်
    if name := customer_data.get("name"):
        payload["properties"]["Customer Name"] = {"rich_text": [{"text": {"content": name}}]}
    if phone := customer_data.get("phone"):
        payload["properties"]["Phone"] = {"rich_text": [{"text": {"content": phone}}]}

    res = await client.post(url, headers=HEADERS, json=payload)
    return res.json(), order_id

async def add_line_item(client, name, qty, main_order_id):
    # Inventory မှာ Item ID ရှာမယ်
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    search_payload = {"filter": {"property": "Product Name", "title": {"equals": name}}}
    search_res = await client.post(search_url, headers=HEADERS, json=search_payload)
    results = search_res.json().get("results", [])
    
    if results:
        item_id = results[0]["id"]
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id}]}
            }
        }
        await client.post(url, headers=HEADERS, json=payload)

@app.get("/full-checkout")
async def full_checkout(items_json: str, name: str = "Customer", phone: str = "N/A"):
    async with httpx.AsyncClient() as client:
        try:
            main_res, display_id = await create_main_order(client, {"name": name, "phone": phone})
            
            if "id" not in main_res:
                return {"status": "Notion Error", "detail": main_res}

            main_id = main_res["id"]
            order_list = json.loads(items_json)
            tasks = [add_line_item(client, item['name'], item['qty'], main_id) for item in order_list]
            await asyncio.gather(*tasks)
            
            return {"status": "Success", "order_id": display_id}
        except Exception as e:
            return {"status": "Error", "msg": str(e)}
