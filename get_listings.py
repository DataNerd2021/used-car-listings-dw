import requests
import pandas as pd
import random
from tqdm import tqdm
from dotenv import load_dotenv
import os

load_dotenv()

zips = pd.read_csv('zip_codes.csv').zip.unique().tolist()
zip_code = random.choice(zips)
num_pages = 10
num_listings = 0
for page in range(1,num_pages+1):
    response = requests.get(f"https://auto.dev/api/listings?apikey={os.getenv('API_KEY')}&page={page}&zip={zip_code}")
    try:
        df = pd.read_csv('listings.csv')
        
        listings = response.json()['records']
        for listing in listings:
            if listing['id'] in df.id.unique():
                continue
            else:
                pd.json_normalize(listing).to_csv('listings.csv', mode='a', header=False, index=False)
        num_listings += len(listings)

    except:
        df = pd.json_normalize(response.json()['records'])
        df.to_csv('listings.csv', index = False)
 
print(pd.read_csv('listings.csv'))
print(f"Appended {num_listings} Listings")  