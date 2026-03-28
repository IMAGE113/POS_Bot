import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
# Line Items DB ID ကို သုံးပါ (DB_ID_3 လို့ မှတ်ခဲ့တာ)
DATABASE_ID = os.environ.get("DB_ID_3") 

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS is Online"}

# POST ကို GET ပြောင်းလိုက်မှ Browser ကနေ စမ်းလို့ရမှာပါ
@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1, price: int = 1000):
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": name}}]},
                "Quantity": {"number": qty},
                "Unit Price": {"number": price}
            }
        )
        return {"message": f"Success! {name} added to Notion."}
    except Exception as e:
        return {"error": str(e)}
