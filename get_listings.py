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
    
    # Ensure the table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_listings_json (
            id SERIAL PRIMARY KEY,
            listing JSONB NOT NULL
        );
    """)
    engine.commit()
    
except Exception as e:
    print(f'Database connection error: {e}')
    exit(1)

# establish zip code iteration pattern
zips = pd.read_csv('zip_codes.csv')

unique_zips = zips['zip'].values.tolist()

# Track recently used zip codes to avoid repetition across sessions
recently_used_zips = []
max_recent_history = 100
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

# Initialize session counter for new listings
session_listings_count = 0

for _ in range(1,11):
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
    print(f'[{_}] Using {zip_code} (History: {len(recently_used_zips)} zip codes)')
    for page in range(1,num_pages+1):
        response = requests.get(f"https://auto.dev/api/listings?apikey={os.getenv('API_KEY')}&page={page}&zip={zip_code}")
        
        try:        
            listings = response.json()['records']
            page_new_listings = 0  # Counter for new listings on this page
            
            for listing in listings:
                # Check if listing ID already exists
                cursor.execute("SELECT COUNT(*) FROM raw_listings_json WHERE listing->>'id' = %s;", (str(listing['id']),))
                exists = cursor.fetchone()[0]
                
                if exists == 0:
                    # Convert the Python dict to JSON string
                    listing_json = json.dumps(listing)
                    cursor.execute("INSERT INTO raw_listings_json(listing) VALUES(%s);", (listing_json,))
                    page_new_listings += 1
                    session_listings_count += 1
                else:
                    continue
            
            # Commit all the inserts for this page
            engine.commit()
            cursor.execute('SELECT COUNT(*) FROM raw_listings_json;')
            row_count = cursor.fetchone()[0]
            print(f'Page {page}: {page_new_listings} new listings added (Session total: {session_listings_count}, Database total: {row_count})')
            time.sleep(5)

        except Exception as e:
            print(f'{e}')

# Print final session summary
print(f"\n{'='*50}")
print(f"SESSION SUMMARY:")
print(f"Total new listings added this session: {session_listings_count}")
print(f"Total listings in database: {row_count}")
print(f"Zip codes used this session: {recently_used_zips}")
print(f"{'='*50}")

# clickOff, mileage, requiresAddressWithLead, price, make, hrefTarget, preCheckThankyouMobile, modelId, bodyStyle, mileageHumanized, active, availableNationwide, alwaysAskForZip,priceUnformatted, partnerType, clickoffUrl, eligibleForFinancing, thumbnailUrlLarge, condition, vdpUrl, allowOneClickSubmit, showRsrp, preCheckThankyou, humanizedSearchLocation, quickPicksEligible, lat, providerId, paidAllowOneClickSubmit, regional, recentPriceDrop, emailOptDefault, bodyType, model, experience, displayColor, distanceFromOrigin, isHot, dealerGroupUuid, showThankyouPage, city, lon, monthlyPayment, createdAt, hideDistance, target, openInNewWindow, cplValue, newPriceAsMsrp, updatedAt, financingExperience, state, year, id, mileageUnformatted, thumbnailUrl, vin, acceptsLeads, noPriceText, regionName, trim, trackingParams, requireEmailOptIn, providerName, providerGroupId, showNewMileage, dealerName, photoUrls, primaryPhotoUrl, priceMobile

# id, vin, year, make, model, trim, mileage, price, condition, bodyStyle, active, eligibleForFinancing, state, city, dealerName, primaryPhotoUrl, photoUrls