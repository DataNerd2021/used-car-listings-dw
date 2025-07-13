import requests
import pandas as pd
import json
import os

listings = pd.read_csv('listings.csv')

all_vins = listings['vin'].to_list()

vehicles = []

iterations = 1


for vin in all_vins[0:11]:
    url = f"https://auto.dev/api/vin/{vin}?apikey={os.getenv('API_KEY')}"
    response = requests.get(url)

    vehicles.append(response.json())
    
    print(iterations)
    iterations += 1

with open('vehicle_descriptions.json', 'a') as file:
    json.dump(vehicles, file, indent=4)