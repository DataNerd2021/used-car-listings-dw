import requests
import pandas as pd

api_key = 'ZrQEPSkKY2hhc2VwYXR0ZWUxMkBnbWFpbC5jb20'

num_pages = 10

for page in range(1,num_pages):
    response = requests.get(f'https://auto.dev/api/listings?apikey={api_key}=&zip=84058&radius=50&body_style[]=crossover&year_min=2021&price_min=20000&price_max=30000&mileage=40000&condition[]=used&driveline[]=AWD&transmission[]=automatic&exclude_no_price=true&page={page}')
    try:
        df = pd.read_csv('listings.csv')
        for listing in response.json()['records']:
            if listing['id'] in df.id.unique():
                continue
            else:
                pd.concat([df, pd.json_normalize(listing)])
    except:
        df = pd.json_normalize(response.json()['records'])
print(df)