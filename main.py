async def add_line_item(client, item_name, qty, main_order_id):
    # ၁။ Inventory မှာ ပစ္စည်းကို နာမည်နဲ့ ရှာမယ်
    search_url = f"https://api.notion.com/v1/databases/{DB_INVENTORY}/query"
    
    # Screenshot အရ "Product Name" လို့ အတိအကျ ပြင်လိုက်ပြီ
    search_payload = {
        "filter": {
            "property": "Product Name", 
            "title": {"equals": item_name}
        }
    }
    
    search_res = await client.post(search_url, headers=HEADERS, json=search_payload)
    results = search_res.json().get("results", [])
    
    if results:
        inventory_page_id = results[0]["id"]
        
        # ၂။ Line Items ထဲမှာ Row အသစ်ဆောက်ပြီး Inventory နဲ့ ချိတ်မယ်
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": DB_LINE_ITEMS},
            "properties": {
                "Line Item": {"title": [{"text": {"content": f"Sale: {item_name}"}}]},
                "Item": {"relation": [{"id": inventory_page_id}]}, 
                "Quantity": {"number": int(qty)},
                "Orders": {"relation": [{"id": main_order_id}]}
            }
        }
        await client.post(url, headers=HEADERS, json=payload)
    else:
        # ဒီနေရာမှာ Error Message ထွက်လာရင် နာမည်လွဲနေလို့ပါ
        print(f"DEBUG: Inventory ထဲမှာ '{item_name}' ကို ရှာမတွေ့ပါ")
