import logging
from dotenv import load_dotenv
import psycopg2

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

db_params = {
    'host': 'postgres-oltp',
    'database':'raw',
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
            CREATE TABLE IF NOT EXISTS raw_vins_decoded (
                id SERIAL PRIMARY KEY,
                vin_decoded JSONB NOT NULL,
                vin VARCHAR(50) NOT NULL
            );
        """)


        engine.commit()
        logger.info('Database connection established successfully')
        return engine, cursor
    
    except Exception as e:
        logger.error(f'Database connection error: {e}')
        raise

def get_unique_vins(cursor) -> set:
    """Get existing VINs from raw_listings_json table"""
    try:
        cursor.execute("SELECT DISTINCT listing->>'vin' FROM raw_listings_json WHERE listing->>'vin' NOT IN (SELECT DISTINCT vin FROM raw_vins_decoded)")
        existing_vins = {row[0] for row in cursor.fetchall()}
        logger.info(f'Loaded {len(existing_vins)} existing VINs.')
        return existing_vins
    except Exception as e:
        logger.warning(f"Could not load existing VINs: {e}")
        return set()

def main():
    engine, cursor = create_database_connection()

    existing_vins = get_unique_vins(cursor)
    print(existing_vins)

if __name__ == "__main__":
    main()