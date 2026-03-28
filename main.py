import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ORDER_ITEMS_DB_ID = os.environ.get("DB_ID_3") 
INVENTORY_DB_ID = os.environ.get("INVENTORY_DB_ID") # Inventory DB ID အသစ်ထည့်ပါ

notion = Client(auth=NOTION_TOKEN)

@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1):
    try:
        # ၁။ Inventory ထဲမှာ ပစ္စည်းနာမည်နဲ့ ID ကို လှမ်းရှာမယ်
        search_res = notion.databases.query(
            database_id=INVENTORY_DB_ID,
            filter={
                "property": "Product Name", # Inventory ထဲက Column နာမည်
                "title": {"equals": name}
            }
        )
        
        # ပစ္စည်းရှာမတွေ့ရင် Error ပြမယ်
        if not search_res["results"]:
            return {"error": f"Item '{name}' not found in Inventory."}
            
        # ရှာတွေ့တဲ့ ပစ္စည်းရဲ့ ID ကို ယူမယ်
        item_id = search_res["results"][0]["id"]

        # ၂။ ရလာတဲ့ ID ကိုသုံးပြီး Order Line Item ထဲကို သွင်းမယ်
        notion.pages.create(
            parent={"database_id": ORDER_ITEMS_DB_ID},
            properties={
                "Line Item": {"title": [{"text": {"content": f"Order: {name}"}}]},
                "Item": {"relation": [{"id": item_id}]}, # Relation နဲ့ ချိတ်လိုက်ပြီ!
                "Quantity": {"number": qty}
            }
        )
        return {"message": f"Successfully added {qty} {name}(s). Formulas linked!"}
        
    except Exception as e:
        return {"error": str(e)}
