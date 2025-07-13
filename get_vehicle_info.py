import requests
import pandas as pd
import json
import os

listings = pd.read_csv('listings.csv')

all_vins = listings['vin'].to_list()

iteration = 1

for vin in all_vins:
    url = f"https://auto.dev/api/vin/{vin}?apikey={os.getenv('API_KEY')}"
    response = requests.get(url)
    # vstack returns a new DataFrame, so we need to reassign
    with open('vehicle_descriptions.json', 'a') as file:
        json.dump(response.json(), file, indent=4)
    
    print(iteration)
    iteration += 1
    