import os

from dotenv import load_dotenv

# O .env é opcional: sem ele, valem os mesmos padrões do docker-compose.yml.
load_dotenv()

ANTIFRAUD_URL = os.environ.get("ANTIFRAUD_URL", "http://localhost:8005")

INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "default_token")
HEADERS = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
