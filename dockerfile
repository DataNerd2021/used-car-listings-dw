FROM python:3.12.11-slim-bullseye AS python3-12-11

WORKDIR /usr/local/app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY listings.csv ./
COPY zip_codes.csv ./
COPY vehicle_descriptions.json ./

COPY get_listings.py ./
COPY get_vehicle_info.py ./

CMD ["python", "get_listings.py"]