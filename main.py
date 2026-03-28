import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

# Render Environment Variables
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
INVENTORY_DB_ID = os.environ.get("DB_ID_1")
LINE_ITEMS_DB_ID = os.environ.get("DB_ID_3")

# Notion Client ကို Initialize လုပ်မယ်
# အောက်ကအတိုင်း အတိအကျ ရေးပေးပါ
notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS Version 3.1 Live"}

@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1):
    try:
        # ၁။ Inventory ထဲမှာ ပစ္စည်းရှာမယ်
        # .query ကို ရှာမတွေ့မှာစိုးလို့ dictionary ပုံစံနဲ့ စစ်ထုတ်မယ်
        db_query = getattr(notion.databases, "query")
        response = db_query(
            database_id=INVENTORY_DB_ID,
            filter={
                "property": "Product Name",
                "title": {"equals": name}
            }
        )
        
        results = response.get("results", [])
        if not results:
            return {"error": f"Item '{name}' not found in Inventory."}
            
        item_id = results[0]["id"]

        # ၂။ Order Line Items ထဲကို Relation နဲ့ ဒေတာသွင်းမယ်
        notion.pages.create(
            parent={"database_id": LINE_ITEMS_DB_ID},
            properties={
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": qty}
            }
        )
        return {"message": f"Success! {name} linked and added."}
        
    except Exception as e:
        return {"error": f"Technical Error: {str(e)}"}
