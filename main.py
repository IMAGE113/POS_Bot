import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

# Render ထဲက ID တွေကို ဆွဲယူမယ်
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
INVENTORY_DB_ID = os.environ.get("DB_ID_1")
LINE_ITEMS_DB_ID = os.environ.get("DB_ID_3")

# Notion Client ကို သတ်မှတ်မယ်
notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's Fully-Auto POS is Live"}

@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1):
    try:
        # ၁။ Inventory ထဲမှာ ပစ္စည်းကို နာမည်နဲ့ ရှာမယ်
        # .databases.query က အလုပ်မလုပ်ရင် .databases.query(...) အတိုင်းပဲ သေချာပြန်ရေးထားပါတယ်
        search_res = notion.databases.query(
            **{
                "database_id": INVENTORY_DB_ID,
                "filter": {
                    "property": "Product Name",
                    "title": {"equals": name}
                }
            }
        )
        
        if not search_res["results"]:
            return {"error": f"Item '{name}' not found in Inventory."}
            
        item_id = search_res["results"][0]["id"]

        # ၂။ Relation (Item) သုံးပြီး ဒေတာသွင်းမယ်
        notion.pages.create(
            parent={"database_id": LINE_ITEMS_DB_ID},
            properties={
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": qty}
            }
        )
        return {"message": f"Success! {name} added with full formulas."}
        
    except Exception as e:
        return {"error": str(e)}
