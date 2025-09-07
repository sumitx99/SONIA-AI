import os
from dotenv import load_dotenv

# Always load .env from project root
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_NAME = os.getenv("DB_NAME", "po1db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

# For debugging
if __name__ == "__main__":
    print("DB_NAME:", DB_NAME)
    print("DB_USER:", DB_USER)
    print("DB_PASSWORD:", DB_PASSWORD)
