import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

# Render Environment Variables ကနေ ဖတ်မယ်
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("LINE_ITEMS_DB_ID")

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS is Online"}

@app.post("/add-item")
def add_item(name: str, qty: int, price: int):
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": name}}]},
                "Quantity": {"number": qty},
                "Unit Price": {"number": price}
            }
        )
        return {"message": "Success"}
    except Exception as e:
        return {"error": str(e)}
