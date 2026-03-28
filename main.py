import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

# Render Environment Variables ထဲကနေ လှမ်းယူမယ်
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DB_ID_3") # Order Line Items Database ID ဖြစ်ရပါမယ်

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def read_root():
    return {"status": "Randy's POS is Online"}

@app.get("/add-item")
def add_item(name: str = "Cola", qty: int = 1):
    try:
        # Notion API ကို ဒေတာပို့မယ်
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                # Aa Line Item (Title type)
                "Line Item": {
                    "title": [
                        {
                            "text": {
                                "content": name
                            }
                        }
                    ]
                },
                # # Quantity (Number type)
                "Quantity": {
                    "number": qty
                }
                # Unit Selling Price က Formula ဖြစ်လို့ ဒီမှာ ထည့်ရေးစရာမလိုပါဘူး
            }
        )
        return {"message": f"Success! {name} added to Notion. Quantity: {qty}"}
    except Exception as e:
        return {"error": str(e)}
