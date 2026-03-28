import os
from notion_client import Client
from fastapi import FastAPI

app = FastAPI()

# Render Environment Variables ထဲမှာ ထည့်ထားတဲ့ Token နဲ့ ID ကို ယူသုံးမယ်
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DB_ID_3") # Order Line Items Database ID ဖြစ်ရပါမယ်

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
                # Aa Line Item ဆိုတဲ့ Column အတွက် (Title type)
                "Line Item": {
                    "title": [
                        {
                            "text": {
                                "content": name
                            }
                        }
                    ]
                },
                # Quantity ဆိုတဲ့ Column အတွက် (Number type)
                "Quantity": {
                    "number": qty
                },
                # Unit Selling Price (သို့မဟုတ်) Selling Price နာမည်ကို Notion မှာ ပြန်စစ်ပါ
                # Screenshot အရ 'Selling Price' လို့ ယူဆပြီး ရေးထားပါတယ်
                "Selling Price": {
                    "number": price
                }
            }
        )
        return {"message": f"Success! {name} added to Notion."}
    except Exception as e:
        # Error တက်ရင် ဘာကြောင့်လဲဆိုတာ မြင်ရအောင် ပြန်ပြပေးမယ်
        return {"error": str(e)}
