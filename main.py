import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
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
                # Aa Symbol ပါတဲ့ Column နာမည် (Title Type)
                "Line Item": {
                    "title": [{"text": {"content": name}}]
                },
                # # Symbol ပါတဲ့ Column နာမည် (Number Type)
                "Quantity": {
                    "number": qty
                },
                # # Symbol ပါတဲ့ Column နာမည် (Number Type)
                # Screenshot အရ 'Unit Selling Price' လို့ တွေ့ရပါတယ်
                "Unit Selling Price": {
                    "number": price
                }
            }
        )
        return {"message": f"Success! {name} added to Notion."}
    except Exception as e:
        return {"error": str(e)}
