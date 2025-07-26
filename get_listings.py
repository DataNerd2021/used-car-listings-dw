#!/usr/bin/python3
import requests
import pandas as pd
import random
from dotenv import load_dotenv
import os
import psycopg2
import json
import time

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

for _ in range(1,101):
    zip_code = random.choice(unique_zips)
    num_pages = 10
    print(f'Using {zip_code}')
    for page in range(1,num_pages+1):
        response = requests.get(f"https://auto.dev/api/listings?apikey={os.getenv('API_KEY')}&page={page}&zip={zip_code}")
        
        try:        
            listings = response.json()['records']
            for listing in listings:
                # Check if listing ID already exists
                cursor.execute("SELECT COUNT(*) FROM raw_listings_json WHERE listing->>'id' = %s;", (str(listing['id']),))
                exists = cursor.fetchone()[0]
                
                if exists == 0:
                    # Convert the Python dict to JSON string
                    listing_json = json.dumps(listing)
                    cursor.execute("INSERT INTO raw_listings_json(listing) VALUES(%s);", (listing_json,))
                else:
                    print(f"Listing ID {listing['id']} already exists, skipping...")
            
            # Commit all the inserts for this page
            engine.commit()
            cursor.execute('SELECT COUNT(*) FROM raw_listings_json;')
            row_count = cursor.fetchone()[0]
            print(f'{row_count} Listings Extracted')
            time.sleep(5)

        except Exception as e:
            print(f'{e}')

# clickOff, mileage, requiresAddressWithLead, price, make, hrefTarget, preCheckThankyouMobile, modelId, bodyStyle, mileageHumanized, active, availableNationwide, alwaysAskForZip,priceUnformatted, partnerType, clickoffUrl, eligibleForFinancing, thumbnailUrlLarge, condition, vdpUrl, allowOneClickSubmit, showRsrp, preCheckThankyou, humanizedSearchLocation, quickPicksEligible, lat, providerId, paidAllowOneClickSubmit, regional, recentPriceDrop, emailOptDefault, bodyType, model, experience, displayColor, distanceFromOrigin, isHot, dealerGroupUuid, showThankyouPage, city, lon, monthlyPayment, createdAt, hideDistance, target, openInNewWindow, cplValue, newPriceAsMsrp, updatedAt, financingExperience, state, year, id, mileageUnformatted, thumbnailUrl, vin, acceptsLeads, noPriceText, regionName, trim, trackingParams, requireEmailOptIn, providerName, providerGroupId, showNewMileage, dealerName, photoUrls, primaryPhotoUrl, priceMobile

# id, vin, year, make, model, trim, mileage, price, condition, bodyStyle, active, eligibleForFinancing, state, city, dealerName, primaryPhotoUrl, photoUrls