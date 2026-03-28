async def add_line_item(client, item_name, qty, main_order_id):
    # ၁။ Inventory ကို Query လုပ်မယ် (Filter မသုံးဘဲ အကုန်ဆွဲထုတ်ကြည့်မယ် - Debug အတွက်)
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    
    # Filter ကို ခဏဖြုတ်ပြီး Inventory ထဲက ပစ္စည်းအားလုံးကို ဆွဲထုတ်ကြည့်မယ်
    search_res = await client.post(search_url, headers=HEADERS, json={})
    all_items = search_res.json().get("results", [])
    
    inventory_id = None
    
    # ပစ္စည်းနာမည်တွေကို တစ်ခုချင်းစီ လိုက်တိုက်စစ်မယ် (စာလုံးအကြီးအသေး မခွဲဘဲ စစ်မယ်)
    for item in all_items:
        # Inventory ထဲက ပစ္စည်းနာမည်ကို ယူမယ်
        try:
            notion_item_name = item["properties"]["Product Name"]["title"][0]["plain_text"]
            
            # မင်းပို့လိုက်တဲ့ နာမည်နဲ့ Notion ထဲက နာမည်ကို စာလုံးအသေးပြောင်းပြီး တိုက်စစ်မယ်
            if notion_item_name.lower().strip() == item_name.lower().strip():
                inventory_id = item["id"]
                break
        except:
            continue

    if inventory_id:
        # ၂။ Relation ချိတ်ပြီး Line Item ဆောက်မယ်
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {item_name}"}}]},
                "Item": {"relation": [{"id": inventory_id}]}, 
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id}]}
            }
        }
        await client.post(url, headers=HEADERS, json=payload)
    else:
        print(f"DEBUG: '{item_name}' ကို Inventory ထဲမှာ လုံးဝရှာမတွေ့ပါ")
