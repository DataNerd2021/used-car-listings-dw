#!/usr/bin/python3
import requests
import pandas as pd
import random
from dotenv import load_dotenv
import os
import psycopg2
import json
import time
import pickle
from datetime import datetime

load_dotenv()

# create postgres connection
db_params = {
    'host':'postgres-oltp',
    'database': 'raw',
    'user': 'postgres',
    'password':'test'}
engine = psycopg2.connect(**db_params)

print('engine created')
try:
    cursor = engine.cursor()
except:
    print('Error')

    # establish zip code iteration pattern
zips = pd.read_csv('zip_codes.csv')

unique_zips = zips['zip'].values.tolist()

# Track recently used zip codes to avoid repetition across sessions
recently_used_zips = []
max_recent_history = 10
zip_history_file = 'zip_code_history.pkl'

# Load previously used zip codes from file
def load_zip_history():
    try:
        with open(zip_history_file, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return []

# Save zip code history to file
def save_zip_history(history):
    with open(zip_history_file, 'wb') as f:
        pickle.dump(history, f)

# Load existing history
recently_used_zips = load_zip_history()
print(f"Loaded {len(recently_used_zips)} previously used zip codes from history")
if recently_used_zips:
    print(f"Recently used zip codes: {recently_used_zips}")

for _ in range(1,101):
    # Choose a zip code that hasn't been used in the last 10 iterations
    available_zips = [zip_code for zip_code in unique_zips if zip_code not in recently_used_zips]
    
    # If all zip codes have been used recently, reset the history
    if not available_zips:
        recently_used_zips = []
        available_zips = unique_zips
    
    zip_code = random.choice(available_zips)
    
    # Add to recently used list and maintain only last 10
    recently_used_zips.append(zip_code)
    if len(recently_used_zips) > max_recent_history:
        recently_used_zips.pop(0)
    
    # Save updated history to file
    save_zip_history(recently_used_zips)
    
    num_pages = 10
    print(f'Using {zip_code} (History: {len(recently_used_zips)} zip codes)')
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
                    continue
            
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