import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
# Line Items DB ID (DB_ID_3) ကို သုံးပါ
DATABASE_ID = os.environ.get("DB_ID_3") 

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS is Online"}

@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1, price: int = 1000):
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                # Notion ထဲက Column နာမည်အမှန်တွေအတိုင်း ပြောင်းထားပါတယ်
                "Product Name": {"title": [{"text": {"content": name}}]},
                "Quantity": {"number": qty},
                "Selling Price": {"number": price}
            }
        )
        return {"message": f"Success! {name} added to Notion."}
    except Exception as e:
        return {"error": str(e)}
