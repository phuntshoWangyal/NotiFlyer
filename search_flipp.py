import requests
import time
import truststore
from database import is_deal_seen, save_deal

#Use the operating system's certificate store so HTTPS works behind antivirus TLS scanning (e.g. Avast).
truststore.inject_into_ssl()

watch_list = ["jasmine rice", "protein powder", "creatine", ]

def search_flipp(query):
    url = "https://cdn-gateflipp.flippback.com/bf/flipp/items/search"    
    params = {"locale":"en-ca",
            "postal_code": "E3B1X9",
            "q":query}

    #Adding a User Agent header makes the request look like its coming from a normal browser and not a python script.
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    response = requests.get(url, params = params, headers = headers)
    print(f"Status code: {response.status_code}")
    # print(f"Response text: {response.text[:300]}") 
    data = response.json()
    
    for item in data["items"]:

        original = item['original_price'] if item['original_price'] else "not listed"

        deal = item['sale_story'] if item['sale_story'] else "flyer special"

        if (is_deal_seen(item['flyer_item_id'])):
            continue
        else :
            print(f"store: {item['merchant_name']}", f"name: {item['name']}", f"current price: {item['current_price']}", 
              f"original price: {original}", f"deal: {deal}")
            save_deal(item['flyer_item_id'], item['name'], item['merchant_name'], item['current_price'])
       


for i in watch_list:
    search_flipp(i)
    time.sleep(2) #waits 2 seconds before the next request. (To prevent the 429 status code error)