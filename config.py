from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL", "15"))
DB_PATH: str = os.getenv("DB_PATH", "kassir_bot.db")
ALLOWED_DOMAINS = {"kassir.ru", "kzn.kassir.ru", "msk.kassir.ru", "spb.kassir.ru"}
