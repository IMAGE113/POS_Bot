import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
INVENTORY_DB_ID = os.environ.get("DB_ID_1")
LINE_ITEMS_DB_ID = os.environ.get("DB_ID_3")

# Version 3.0.0 အတွက် Client သတ်မှတ်ချက်
notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS Version 3.0 Online"}

@app.get("/add-item")
async def add_item(name: str = "Cola", qty: int = 1):
    try:
        # ၁။ Inventory မှာ ရှာမယ် (Version 3.0 query ပုံစံ)
        search_res = notion.databases.query(
            database_id=INVENTORY_DB_ID,
            filter={
                "property": "Product Name",
                "title": {"equals": name}
            }
        )
        
        # results ထဲမှာ ဘာမှမရှိရင် error ပြမယ်
        results = search_res.get("results")
        if not results:
            return {"error": f"Item '{name}' not found in Inventory."}
            
        item_id = results[0]["id"]

        # ၂။ Order Line Item ထဲကို Relation နဲ့ ဒေတာသွင်းမယ်
        notion.pages.create(
            parent={"database_id": LINE_ITEMS_DB_ID},
            properties={
                "Line Item": {"title": [{"text": {"content": f"Sale: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]},
                "Quantity": {"number": qty}
            }
        )
        return {"message": f"Success! {name} linked to Inventory."}
        
    except Exception as e:
        # Error တက်ရင် ဘာကြောင့်လဲဆိုတာကို သေချာထုတ်ပြမယ်
        return {"error": str(e)}
