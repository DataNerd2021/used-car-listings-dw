#!/usr/bin/python3
import requests
import pandas as pd
from dotenv import load_dotenv
import os
import psycopg2
import json
import time
import pickle
from typing import List, Dict, Any
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Database connection parameters
db_params = {
    'host': 'postgres-oltp',
    'database': 'raw',
    'user': 'postgres',
    'password': 'test'
}

def create_database_connection():
    """Create and return database connection with error handling"""
    try:
        engine = psycopg2.connect(**db_params)
        cursor = engine.cursor()
        
        # Ensure the table exists with current schema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_listings_json (
                id SERIAL PRIMARY KEY,
                listing JSONB NOT NULL
            );
        """)
        
        
        engine.commit()
        logger.info("Database connection established successfully")
        return engine, cursor
        
    except Exception as e:
        logger.error(f'Database connection error: {e}')
        raise

def load_zip_codes() -> List[str]:
    """Load zip codes from CSV file"""
    try:
        zips = pd.read_csv('zip_codes.csv')
        unique_zips = zips['zip'].values.tolist()
        logger.info(f"Loaded {len(unique_zips)} zip codes")
        return unique_zips
    except FileNotFoundError:
        logger.error("zip_codes.csv not found. Please ensure the file exists.")
        raise
    except Exception as e:
        logger.error(f"Error loading zip codes: {e}")
        raise

def load_completed_combinations() -> List[str]:
    """Load combinations (zip code + body style) that have been completed from file"""
    completed_file = 'completed_combinations.pkl'
    try:
        with open(completed_file, 'rb') as f:
            completed = pickle.load(f)
            logger.info(f"Loaded {len(completed)} completed zip/body-style combinations from log")
            return completed
    except FileNotFoundError:
        logger.info("No completed combinations log found. Starting fresh.")
        return []

def save_completed_combinations(completed: List[str]):
    """Persist completed combinations (zip code + body style) to file"""
    completed_file = 'completed_combinations.pkl'
    with open(completed_file, 'wb') as f:
        pickle.dump(completed, f)

def get_existing_listing_ids(cursor) -> set:
    """Get existing listing IDs from database for duplicate checking"""
    try:
        cursor.execute("SELECT listing->>'id' FROM raw_listings_json WHERE listing->>'id' IS NOT NULL;")
        existing_ids = {row[0] for row in cursor.fetchall()}
        logger.info(f"Loaded {len(existing_ids)} existing listing IDs for duplicate checking")
        return existing_ids
    except Exception as e:
        logger.warning(f"Could not load existing listing IDs: {e}")
        return set()

def fetch_listings_page(api_key: str, zip_code: str, body_style: str, page: int) -> Dict[str, Any]:
    """Fetch a single page of listings with proper error handling"""
    url = f"https://auto.dev/api/listings?apikey={api_key}&body_style[]={body_style}&page={page}&zip={zip_code}"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Check if page has results
        if not data.get('records') or len(data['records']) == 0:
            logger.info(f"No results found for page {page} (zip: {zip_code}, body_style: {body_style})")
            return {'records': [], 'has_more': False}
        
        # Check if there are more pages
        has_more = len(data['records']) > 0 and page < 50  # Safety limit
        
        return {
            'records': data['records'],
            'has_more': has_more
        }
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            logger.info(f"Page {page} not found (404) - skipping")
            return {'records': [], 'has_more': False}
        else:
            logger.warning(f"HTTP error on page {page}: {e}")
            return {'records': [], 'has_more': False}
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request error on page {page}: {e}")
        return {'records': [], 'has_more': False}
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error on page {page}: {e}")
        return {'records': [], 'has_more': False}
    except Exception as e:
        logger.warning(f"Unexpected error on page {page}: {e}")
        return {'records': [], 'has_more': False}

def process_listings_batch(cursor, listings: List[Dict], existing_ids: set) -> int:
    """Process a batch of listings and return count of new ones added"""
    new_listings = 0
    batch_inserts = []
    
    for listing in listings:
        listing_id = str(listing.get('id', ''))
        
        # Skip if no ID or already exists
        if not listing_id or listing_id in existing_ids:
            continue
        
        # Prepare for batch insert
        listing_json = json.dumps(listing)
        batch_inserts.append((listing_json,))
        existing_ids.add(listing_id)  # Add to set to avoid duplicates in same batch
        new_listings += 1
    
    # Batch insert all new listings
    if batch_inserts:
        try:
            cursor.executemany(
                "INSERT INTO raw_listings_json(listing) VALUES(%s);",
                batch_inserts
            )
            logger.info(f"Batch inserted {new_listings} new listings")
        except Exception as e:
            logger.error(f"Error in batch insert: {e}")
            # Fallback to individual inserts
            for listing_json, in batch_inserts:
                try:
                    cursor.execute(
                        "INSERT INTO raw_listings_json(listing) VALUES(%s);",
                        (listing_json,)
                    )
                except Exception as insert_error:
                    logger.warning(f"Failed to insert listing: {insert_error}")
    
    return new_listings

def main():
    """Main function to orchestrate the listing collection process"""
    # Initialize database connection
    engine, cursor = create_database_connection()
    
    # Load zip codes and completed combinations log
    unique_zips = load_zip_codes()
    completed_combinations = load_completed_combinations()
    
    # Load existing listing IDs for duplicate checking
    existing_ids = get_existing_listing_ids(cursor)
    
    # Session tracking
    session_listings_count = 0
    session_iterations = 0
    max_iterations = 500
    
    # Body styles to cycle through
    body_styles = ['SUV', 'Sedan', 'Coupe', 'Crossover', 'Truck', 'Minivan', 'Wagon', 'Hatchback']

    # Build all possible zip/body-style combinations once
    all_combinations = [f"{zip_code}-{body_style}" for zip_code in unique_zips for body_style in body_styles]
    pending_combinations = [combo for combo in all_combinations if combo not in completed_combinations]
    
    logger.info(f"Starting listing collection with {len(unique_zips)} zip codes available")
    
    if not pending_combinations:
        logger.info("All zip code and body style combinations have already been completed. Nothing to do.")
        # Close database connection
        cursor.close()
        engine.close()
        logger.info("Database connection closed")
        return

    logger.info(f"Starting listing collection with {len(unique_zips)} zip codes available")
    logger.info(f"Total combinations: {len(all_combinations)} | Completed: {len(completed_combinations)} | Pending: {len(pending_combinations)}")

    for iteration, selected_combination in enumerate(pending_combinations[:max_iterations], start=1):
        session_iterations += 1
        zip_code, body_style = selected_combination.split('-', 1)

        logger.info(f'[{iteration}] Processing {zip_code} ({body_style}) - Completed so far: {len(completed_combinations)}')
        
        # Fetch all pages for this zip/body_style combination
        page = 1
        total_pages_processed = 0
        iteration_new_listings = 0
        
        while page <= 50:  # Safety limit
            result = fetch_listings_page(os.getenv('API_KEY'), zip_code, body_style, page)
            
            if not result['records']:
                logger.info(f"No more results for {zip_code} {body_style} after page {page-1}")
                break
            
            # Process the listings
            new_count = process_listings_batch(cursor, result['records'], existing_ids)
            iteration_new_listings += new_count
            session_listings_count += new_count
            total_pages_processed += 1
            
            logger.info(f'Page {page}: {new_count} new listings (Iteration total: {iteration_new_listings})')
            
            # Check if we should continue to next page
            if not result['has_more']:
                break
            
            page += 1
            
            # Small delay to be respectful to the API
            time.sleep(0.5)
        
        # Commit after each iteration
        try:
            engine.commit()
            logger.info(f'Iteration {iteration} complete: {iteration_new_listings} new listings, {total_pages_processed} pages processed')
            # Mark this combination as completed only after successful commit
            completed_combinations.append(selected_combination)
            save_completed_combinations(completed_combinations)
        except Exception as e:
            logger.error(f"Error committing iteration {iteration}: {e}")
            engine.rollback()
        
        # Progress update every 10 iterations
        if iteration % 10 == 0:
            logger.info(f"Progress: {iteration}/{max_iterations} iterations, {session_listings_count} total new listings")
    
    # Final summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SESSION SUMMARY:")
    logger.info(f"Total iterations completed: {session_iterations}")
    logger.info(f"Total new listings added: {session_listings_count}")
    logger.info(f"Combinations completed this session: {min(session_iterations, len(pending_combinations))}")
    logger.info(f"Cumulative completed combinations: {len(completed_combinations)}")
    logger.info(f"Remaining combinations: {max(0, len(all_combinations) - len(completed_combinations))}")
    logger.info(f"{'='*60}")
    
    # Close database connection
    cursor.close()
    engine.close()
    logger.info("Database connection closed")

if __name__ == "__main__":
    main()