import os
import logging
from dotenv import load_dotenv

load_dotenv()

# --- Bot Configuration ---
# Prefix for bot commands (e.g., !quiz, !help)
BOT_PREFIX = "!"

# Maximum number of questions allowed in a single quiz session
MAX_QUIZ_QUESTIONS = 30

# Timeout settings for quiz sessions
QUIZ_TIMEOUT_MINUTES = 5
QUIZ_TIMEOUT_SECONDS = 300  # Calculated from QUIZ_TIMEOUT_MINUTES for internal use
QUIZ_SESSION_TIMEOUT_SECONDS = 300 # Inactivity timeout for a quiz session
QUIZ_TIMEOUT_CHECK_INTERVAL_MINUTES = 1 # How often the bot checks for timed-out quizzes

# Discord Bot Token - Retrieved from environment variables for security
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# List of Discord User IDs who have administrative privileges for the bot.
# Enable Developer Mode in Discord, then right-click your profile and select "Copy ID" to get your ID.
ADMIN_USER_IDS = [
    int(uid) for uid in os.getenv("ADMIN_USER_IDS", "").split(',') if uid.strip()
]

# Groq API Key - Retrieved from environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- Groq API Settings ---
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROQ_DEFAULT_TEMPERATURE = 0.7
GROQ_DEFAULT_MAX_TOKENS = 4000

# --- Database Configuration ---
# Directory where the SQLite database file will be stored.
# Defaults to "C:\CalcBotData" if the DB_DIRECTORY environment variable is not set.
DB_DIRECTORY = os.getenv("DB_DIRECTORY", "C:\\CalcBotData")

# Full path to the SQLite database file.
DATABASE_URL = os.path.join(DB_DIRECTORY, "questions.db")

# --- Logging Configuration ---
# Sets the minimum level of messages to log (e.g., INFO, DEBUG, WARNING, ERROR, CRITICAL)
LOG_LEVEL = logging.INFO
# Path to the log file
LOG_FILE = "logs/bot.log"
# Format of log messages
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# Date and time format within log messages
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- Default Quiz Generation Parameters ---
# Default number of questions when a quiz is started without specifying a count
DEFAULT_QUIZ_QUESTION_COUNT = 3
# Default difficulty for generated questions (None for random, or 'Easy', 'Medium', 'Hard')
DEFAULT_QUIZ_DIFFICULTY = None
# Default unit for generated questions (None for random, or a specific unit number)
DEFAULT_QUIZ_UNIT = None