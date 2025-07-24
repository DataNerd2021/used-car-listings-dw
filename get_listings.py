#!/usr/bin/python3
import requests
import pandas as pd
import random
from dotenv import load_dotenv
import os
import psycopg2
import json

load_dotenv()

db_params = {
    'host':'postgres-oltp',
    'database': 'raw',
    'user': 'postgres',
    'password':'test'}
engine = psycopg2.connect(**db_params)

print('engine created')
try:
    cursor = engine.cursor()

    # with open('zip_codes.csv', 'r') as f:
    #     f.readline()
    #     cursor.copy_from(f, 'zip_codes', sep=',')
    # engine.commit()
    # print('Data Uploaded')
except:
    print('Error')
zips = pd.read_csv('zip_codes.csv')

unique_zips = zips['zip'].values.tolist()
zip_code = random.choice(unique_zips)

num_pages = 2
num_listings = 0
for page in range(1,num_pages+1):
    response = requests.get(f"https://auto.dev/api/listings?apikey={os.getenv('API_KEY')}&page={page}&zip={zip_code}")
    
    try:        
        listings = response.json()['records']
        for listing in listings:
            # Convert the Python dict to JSON string
            listing_json = json.dumps(listing)
            cursor.execute("INSERT INTO raw_listings_json(listing) VALUES(%s);", (listing_json,))
            num_listings += 1
        # Commit all the inserts for this page
        engine.commit()
        print(f'{num_listings} Listings added to Table')

    except Exception as e:
        print(f'{e}')
