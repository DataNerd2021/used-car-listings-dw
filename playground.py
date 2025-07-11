import requests
import pandas as pd

api_key = 'ZrQEPSkKY2hhc2VwYXR0ZWUxMkBnbWFpbC5jb20'

num_pages = 10

for page in range(1,num_pages):
    response = requests.get(f'https://auto.dev/api/listings?apikey={api_key}&page={page}')
    try:
        df = pd.read_csv('listings.csv')
        for listing in response.json()['records']:
            if listing['id'] in df.id.unique():
                continue
            else:
                pd.concat([df, pd.json_normalize(listing)])
    except:
        df = pd.json_normalize(response.json()['records'])
        df.to_csv('listings.csv', index = False)
        
print(df)