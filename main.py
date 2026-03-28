import os
import httpx
import json
import asyncio
from fastapi import FastAPI

app = FastAPI()

# Environment Variables
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
INVENTORY_DB_ID = os.environ.get("DB_ID_1")
LINE_ITEMS_DB_ID = os.environ.get("DB_ID_3")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ၁။ ပစ္စည်းတစ်ခုချင်းစီကို Notion ထဲသွင်းမယ့် Internal Function
async def process_single_item(client, name, qty):
    try:
        # Inventory မှာ ID အရင်ရှာမယ်
        search_url = f"https://api.notion.com/v1/databases/{INVENTORY_DB_ID}/query"
        search_payload = {"filter": {"property": "Product Name", "title": {"equals": name}}}
        
        search_res = await client.post(search_url, headers=HEADERS, json=search_payload)
        results = search_res.json().get("results", [])
        
        if not results:
            return {"item": name, "status": "Error: Not found in Inventory"}
            
        item_id = results[0]["id"]

        # Line Items ထဲကို ဒေတာသွင်းမယ်
        create_url = "https://api.notion.com/v1/pages"
        create_payload = {
            "parent": {"database_id": LINE_ITEMS_DB_ID},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": qty}
            }
        }
        await client.post(create_url, headers=HEADERS, json=create_payload)
        return {"item": name, "status": "Success"}
        
    except Exception as e:
        return {"item": name, "status": f"Error: {str(e)}"}

@app.get("/add-bulk-items")
async def add_bulk_items(items_json: str):
    """
    Example input: items_json='[{"name": "Coffee", "qty": 2}, {"name": "Tea", "qty": 1}]'
    """
    async with httpx.AsyncClient() as client:
        try:
            # AI ဆီကလာတဲ့ JSON string ကို list အဖြစ်ပြောင်းမယ်
            order_list = json.loads(items_json)
            
            # ပစ္စည်းအားလုံးကို တပြိုင်နက် (Parallel) အလုပ်လုပ်ခိုင်းမယ်
            tasks = [process_single_item(client, item['name'], item['qty']) for item in order_list]
            final_results = await asyncio.gather(*tasks)
            
            return {
                "message": "Bulk processing completed",
                "details": final_results
            }
            
        except Exception as e:
            return {"error": f"Bulk Processing Error: {str(e)}"}
