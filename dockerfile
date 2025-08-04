FROM python:3.12.11-slim-bullseye AS python3-12-11

WORKDIR /usr/local/app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY zip_codes.csv ./

COPY get_listings.py ./
COPY get_vehicle_info.py ./
COPY manage_zip_history.py ./
COPY get_listing_info.py ./

# Create data directory for persistent files
RUN mkdir -p /usr/local/app/data

CMD ["python", "get_listings.py"]