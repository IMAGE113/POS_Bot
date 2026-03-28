import os
import httpx
from fastapi import FastAPI

app = FastAPI()

# Environment Variables
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
INVENTORY_DB_ID = os.environ.get("DB_ID_1")
LINE_ITEMS_DB_ID = os.environ.get("DB_ID_3")

# Notion API Headers
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.get("/")
def read_root():
    return {"status": "Randy's POS Bypass Version Live"}

@app.get("/add-item")
async def add_item(name: str = "Cola", qty: int = 1):
    async with httpx.AsyncClient() as client:
        try:
            # ၁။ Inventory ထဲမှာ ပစ္စည်းရှာမယ် (Direct API Call)
            search_url = f"https://api.notion.com/v1/databases/{INVENTORY_DB_ID}/query"
            search_data = {
                "filter": {
                    "property": "Product Name",
                    "title": {"equals": name}
                }
            }
            
            search_res = await client.post(search_url, headers=HEADERS, json=search_data)
            search_res_json = search_res.json()
            
            results = search_res_json.get("results", [])
            if not results:
                return {"error": f"Item '{name}' not found in Inventory DB."}
            
            item_id = results[0]["id"]

            # ၂။ Order Line Items ထဲကို Relation နဲ့ ဒေတာသွင်းမယ်
            create_url = "https://api.notion.com/v1/pages"
            create_data = {
                "parent": {"database_id": LINE_ITEMS_DB_ID},
                "properties": {
                    "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                    "Item": {"relation": [{"id": item_id}]},
                    "Quantity": {"number": qty}
                }
            }
            
            create_res = await client.post(create_url, headers=HEADERS, json=create_data)
            
            if create_res.status_code == 200:
                return {"message": f"Success! {name} linked and added."}
            else:
                return {"error": create_res.text}
                
        except Exception as e:
            return {"error": f"Technical Bypass Error: {str(e)}"}
