#!/usr/bin/python3
import requests
import pandas as pd
from dotenv import load_dotenv
import os
import psycopg2
import json
import time
import pickle
from typing import List, Dict, Any, Optional
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from psycopg2 import pool

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

# Database connection pool
db_pool = None

def initialize_db_pool():
    """Initialize the database connection pool"""
    global db_pool
    try:
        db_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=20,  # Adjust based on MAX_WORKERS
            **db_params
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize connection pool: {e}")
        raise

def get_db_connection():
    """Get a connection from the pool"""
    if db_pool is None:
        initialize_db_pool()
    return db_pool.getconn()

def return_db_connection(conn):
    """Return a connection to the pool"""
    if db_pool is not None:
        db_pool.putconn(conn)

# Threading locks
existing_ids_lock = threading.Lock()
completed_lock = threading.Lock()

# Rate limit config (env-tunable)
API_RPS = float(os.getenv('API_RPS', '1.0'))           # allowed requests per second across all threads
API_BURST = int(os.getenv('API_BURST', '2'))           # burst capacity for token bucket
API_MAX_RETRIES = int(os.getenv('API_MAX_RETRIES', '5'))
PAGE_DELAY_SECONDS = float(os.getenv('PAGE_DELAY_SECONDS', '0.5'))  # base delay between pages
JITTER_SECONDS = float(os.getenv('JITTER_SECONDS', '0.3'))

class RateLimiter:
    def __init__(self, rate: float, burst: int):
        self.rate = max(rate, 0.1)
        self.capacity = max(burst, 1)
        self.tokens = self.capacity
        self.updated_at = time.monotonic()
        self.lock = threading.Lock()
    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                need = (1.0 - self.tokens) / self.rate
            time.sleep(need)

rate_limiter = RateLimiter(API_RPS, API_BURST)

# Per-thread HTTP session with retries
_thread_local = threading.local()

def get_session() -> requests.Session:
    s = getattr(_thread_local, 'session', None)
    if s is not None:
        return s
    s = requests.Session()
    retries = Retry(
        total=API_MAX_RETRIES,
        backoff_factor=0.5,  # base exponential backoff for retryable codes
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    _thread_local.session = s
    return s

def create_database_connection():
    """Create and return database connection with error handling"""
    try:
        engine = get_db_connection()
        cursor = engine.cursor()
        
        # Ensure the table exists with current schema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_listings_json (
                id SERIAL PRIMARY KEY,
                listing JSONB NOT NULL
            );
        """)
        
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_raw_listings_listing_id
            ON raw_listings_json ((listing->>'id'));
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
    """Fetch a single page of listings with proper error handling and backoff"""
    url = f"https://auto.dev/api/listings?apikey={api_key}&body_style[]={body_style}&page={page}&zip={zip_code}&sort_filter=created_at:desc"

    session = get_session()
    attempt = 0
    while attempt < API_MAX_RETRIES:
        attempt += 1
        try:
            # Global rate limit across threads
            rate_limiter.acquire()

            resp = session.get(url, timeout=30)
            if resp.status_code == 429:
                # Honor Retry-After if present; else exponential backoff + jitter
                retry_after = resp.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait_s = float(retry_after)
                    except ValueError:
                        wait_s = min(60.0, 2 ** attempt)
                else:
                    wait_s = min(60.0, 2 ** attempt)
                wait_s += random.uniform(0, JITTER_SECONDS)
                logger.warning(f"429 received for {zip_code}/{body_style} page {page}. Backing off {wait_s:.2f}s (attempt {attempt}/{API_MAX_RETRIES})")
                time.sleep(wait_s)
                continue

            resp.raise_for_status()
            data = resp.json()

            if not data.get('records') or len(data['records']) == 0:
                logger.info(f"No results found for page {page} (zip: {zip_code}, body_style: {body_style})")
                return {'records': [], 'has_more': False}

            has_more = len(data['records']) > 0 and page < 50  # Safety limit
            return {'records': data['records'], 'has_more': has_more}

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            wait_s = min(60.0, 2 ** attempt) + random.uniform(0, JITTER_SECONDS)
            logger.warning(f"Transient error on {zip_code}/{body_style} page {page}: {e} — retrying in {wait_s:.2f}s (attempt {attempt}/{API_MAX_RETRIES})")
            time.sleep(wait_s)
        except Exception as e:
            logger.warning(f"Unexpected error on page {page}: {e}")
            return {'records': [], 'has_more': False}

    logger.error(f"Exhausted retries for {zip_code}/{body_style} page {page}")
    return {'records': [], 'has_more': False}

def process_listings_batch(cursor, listings: List[Dict], existing_ids: set, existing_ids_lock: Optional[threading.Lock] = None) -> int:
    """Process a batch of listings and return count of new ones added - CORRECTED VERSION"""
    new_listings = 0
    batch_inserts = []

    # Prepare all listings for insertion (let database handle duplicates)
    for listing in listings:
        listing_id = str(listing.get('id', ''))
        if not listing_id:
            continue

        listing_json = json.dumps(listing)
        batch_inserts.append((listing_json,))

    if batch_inserts:
        try:
            # Use individual inserts with RETURNING to get exact count
            for listing_json, in batch_inserts:
                cursor.execute(
                    "INSERT INTO raw_listings_json(listing) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id;",
                    (listing_json,)
                )
                # If a row was returned, it was actually inserted
                if cursor.fetchone() is not None:
                    new_listings += 1
            
            logger.info(f"Batch processed {len(batch_inserts)} listings, actually inserted {new_listings} new listings")
            
        except Exception as e:
            logger.error(f"Error in batch insert: {e}")

    return new_listings

def process_listings_batch_optimized(cursor, listings: List[Dict]) -> int:
    if not listings:
        return 0
    
    # Get count before insertion
    cursor.execute("SELECT COUNT(*) FROM raw_listings_json;")
    count_before = cursor.fetchone()[0]
    
    # Prepare batch insert
    batch_data = [(json.dumps(listing),) for listing in listings if listing.get('id')]
    
    # Execute batch insert
    cursor.executemany(
        "INSERT INTO raw_listings_json(listing) VALUES (%s) ON CONFLICT DO NOTHING;",
        batch_data
    )
    
    # Get count after insertion
    cursor.execute("SELECT COUNT(*) FROM raw_listings_json;")
    count_after = cursor.fetchone()[0]
    
    return count_after - count_before

def process_combination_task(
    selected_combination: str,
    existing_ids: set,
    completed_combinations: list,
    existing_ids_lock: threading.Lock,
    completed_lock: threading.Lock,
) -> tuple[int, int, str]:
    zip_code, body_style = selected_combination.split('-', 1)
    engine, cursor = create_database_connection()
    page = 1
    total_pages_processed = 0
    total_new_listings = 0
    
    # OPTIMIZATION: Accumulate multiple pages before inserting
    accumulated_listings = []
    batch_size = 15  # Process 15 pages before inserting

    try:
        while page <= 50:
            result = fetch_listings_page(os.getenv('API_KEY'), zip_code, body_style, page)
            if not result['records']:
                break

            # Accumulate listings instead of processing immediately
            accumulated_listings.extend(result['records'])
            total_pages_processed += 1

            # Insert when we have enough pages or at the end
            if len(accumulated_listings) >= batch_size * 20 or not result['has_more']:  # Assume ~20 listings per page
                if accumulated_listings:
                    new_count = process_listings_batch(cursor, accumulated_listings, existing_ids, existing_ids_lock)
                    total_new_listings += new_count
                    accumulated_listings = []  # Clear after processing

            if not result['has_more']:
                break

            page += 1
            time.sleep(PAGE_DELAY_SECONDS + random.uniform(0, JITTER_SECONDS))

        # Process any remaining accumulated listings
        if accumulated_listings:
            new_count = process_listings_batch(cursor, accumulated_listings, existing_ids, existing_ids_lock)
            total_new_listings += new_count

        engine.commit()

        # Mark as completed after successful commit
        with completed_lock:
            completed_combinations.append(selected_combination)
            save_completed_combinations(completed_combinations)

        return total_new_listings, total_pages_processed, selected_combination

    except Exception as e:
        logger.error(f"Error processing {selected_combination}: {e}")
        engine.rollback()
        return 0, total_pages_processed, selected_combination
    finally:
        cursor.close()
        return_db_connection(engine)  # Return to pool instead of closing

def prioritize_combinations(combinations, zip_population_data):
    """Prioritize zip codes with higher population for better yield"""
    scored_combinations = []
    for combo in combinations:
        zip_code = combo.split('-')[0]
        population = zip_population_data.get(zip_code, 1000)
        score = population  # Higher population = higher priority
        scored_combinations.append((score, combo))
    
    return [combo for _, combo in sorted(scored_combinations, reverse=True)]

def get_adaptive_delay(last_response_time, error_count):
    base_delay = PAGE_DELAY_SECONDS
    if error_count > 0:
        base_delay *= (1 + error_count * 0.5)  # Exponential backoff
    if last_response_time > 2.0:  # Slow response
        base_delay *= 1.2
    return base_delay + random.uniform(0, JITTER_SECONDS)

def main():
    """Main function to orchestrate the listing collection process - OPTIMIZED VERSION"""
    # Initialize database connection pool
    initialize_db_pool()
    
    # Load zip codes and completed combinations log
    unique_zips = load_zip_codes()
    completed_combinations = load_completed_combinations()
    
    # OPTIMIZATION: Skip loading existing IDs since we have DB-level uniqueness
    existing_ids = set()  # Start with empty set, let DB handle duplicates
    
    # Session tracking
    session_listings_count = 0
    session_iterations = 0
    max_iterations = 200
    session_start_time = time.time()  # Track session start time
    
    # Body styles to cycle through
    body_styles = ['SUV', 'Sedan', 'Coupe', 'Crossover', 'Truck', 'Minivan', 'Wagon', 'Hatchback']

    # Build all possible combinations and filter pending
    all_combinations = [f"{zip_code}-{body_style}" for zip_code in unique_zips for body_style in body_styles]
    pending_combinations = [combo for combo in all_combinations if combo not in completed_combinations]

    if not pending_combinations:
        logger.info("All zip code and body style combinations have already been completed. Nothing to do.")
        return

    max_workers = int(os.getenv('MAX_WORKERS', str(max(1, min(8, int(API_BURST * 2))))))
    worklist = pending_combinations[:max_iterations]

    logger.info(f"Starting OPTIMIZED listing collection with {len(unique_zips)} zip codes available")
    logger.info(f"Total combinations: {len(all_combinations)} | Completed: {len(completed_combinations)} | Pending: {len(pending_combinations)}")
    logger.info(f"Running with max_workers={max_workers}, queueing {len(worklist)} combinations this run")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_combination_task,
                combo,
                existing_ids,
                completed_combinations,
                existing_ids_lock,
                completed_lock
            ): combo
            for combo in worklist
        }

        for i, future in enumerate(as_completed(futures), start=1):
            try:
                new_count, pages, combo = future.result()
                session_listings_count += new_count
                session_iterations += 1
                
                # Calculate elapsed time
                elapsed_time = time.time() - session_start_time
                elapsed_hours = int(elapsed_time // 3600)
                elapsed_minutes = int((elapsed_time % 3600) // 60)
                elapsed_seconds = int(elapsed_time % 60)
                
                # Show elapsed time every 10 iterations
                if session_iterations % 10 == 0:
                    logger.info(f"[{i}/{len(worklist)}] Completed {combo}: {new_count} new listings, {pages} pages — session total: {session_listings_count} | Elapsed: {elapsed_hours:02d}:{elapsed_minutes:02d}:{elapsed_seconds:02d}")
                else:
                    logger.info(f"[{i}/{len(worklist)}] Completed {combo}: {new_count} new listings, {pages} pages — session total: {session_listings_count}")
                    
            except Exception as e:
                logger.error(f"Worker failed: {e}")
    
    # Calculate final elapsed time
    total_elapsed_time = time.time() - session_start_time
    total_hours = int(total_elapsed_time // 3600)
    total_minutes = int((total_elapsed_time % 3600) // 60)
    total_seconds = int(total_elapsed_time % 60)
    
    # Final summary
    logger.info(f"\n{'='*60}")
    logger.info(f"OPTIMIZED SESSION SUMMARY:")
    logger.info(f"Total iterations completed: {session_iterations}")
    logger.info(f"Total new listings added: {session_listings_count}")
    logger.info(f"Combinations completed this session: {min(session_iterations, len(pending_combinations))}")
    logger.info(f"Cumulative completed combinations: {len(completed_combinations)}")
    logger.info(f"Remaining combinations: {max(0, len(all_combinations) - len(completed_combinations))}")
    logger.info(f"Total session time: {total_hours:02d}:{total_minutes:02d}:{total_seconds:02d}")
    logger.info(f"{'='*60}")
    logger.info(f"Used max_workers={max_workers}")
    
    # Clean up connection pool
    if db_pool is not None:
        db_pool.closeall()
    logger.info("Database connection pool closed")

if __name__ == "__main__":
    main()