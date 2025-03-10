import asyncio
import os
import re
import logging
import traceback
from instaloader import Instaloader, Post, InstaloaderException
from telegram import Update
from telegram.ext import CallbackContext

# Initialize Instaloader
L = Instaloader()

# Download queue and lock
download_queue = []
download_lock = asyncio.Lock()

# Regex to validate Instagram links
INSTAGRAM_REGEX = r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)/?"

async def process_download(context: CallbackContext):
    """Continuously processes the queued media downloads."""
    global download_queue

    while True:  # Keeps checking for new downloads
        async with download_lock:
            if not download_queue:
                await asyncio.sleep(5)  # Keep loop alive
                continue

            link, user_id = download_queue.pop(0)  # Get next task

        chat_id = user_id
        try:
            # Validate the link before processing
            match = re.match(INSTAGRAM_REGEX, link)
            if not match:
                await context.bot.send_message(chat_id, "❌ Invalid Instagram link!")
                continue
            shortcode = match.group(1)  # Extract shortcode safely

            post = Post.from_shortcode(L.context, shortcode)

            # Simulated progress bar (to be improved later)
            total_size = 100
            downloaded = 0
            message = await context.bot.send_message(chat_id=chat_id, text=f"⏳ Downloading... {downloaded}%")

            while downloaded < total_size:
                await asyncio.sleep(1)
                downloaded += 10
                if downloaded > total_size:
                    downloaded = total_size
                try:
                    await message.edit_text(f"⏳ Downloading... {downloaded}%")
                except Exception as e:
                    logging.error(f"Failed to update progress: {e}")

            # Download post to disk
            L.download_post(post, target="downloads")

            # Define file path
            file_path = f"downloads/{post.shortcode}.mp4" if post.is_video else f"downloads/{post.shortcode}.jpg"

            # Send the downloaded file
            if post.is_video:
                await context.bot.send_video(chat_id, open(file_path, "rb"), caption="🎥 Download Complete!")
            else:
                await context.bot.send_photo(chat_id, open(file_path, "rb"), caption="🖼️ Download Complete!")

            # Clean up the file
            os.remove(file_path)

        except InstaloaderException:
            await context.bot.send_message(chat_id, "❌ Failed to download. The post might be private or unavailable.")
        except Exception as e:
            logging.error(f"Error processing download: {traceback.format_exc()}")

        await asyncio.sleep(2)  # Pause before checking for next item

#step 2

from aiolimiter import AsyncLimiter
import time

# Initialize rate limiter (1 request every 3 seconds)
limiter = AsyncLimiter(1, 3)

# Dictionary to track user request timestamps
user_last_request = {}

async def rate_limited(update: Update, context: CallbackContext):
    """Check if user is sending requests too frequently."""
    user_id = update.effective_user.id
    current_time = time.time()

    if user_id in user_last_request:
        time_since_last_request = current_time - user_last_request[user_id]
        if time_since_last_request < 3:
            await update.message.reply_text("⏳ Please wait before sending another request.")
            return False  # Deny request

    user_last_request[user_id] = current_time  # Update last request time
    return True  # Allow request

async def download_media(update: Update, context: CallbackContext):
    """Handles media download requests with rate limiting."""
    if not await rate_limited(update, context):  # Enforce rate limiting
        return  

    user_id = update.effective_user.id
    link = update.message.text.strip()

    # Validate link
    match = re.match(INSTAGRAM_REGEX, link)
    if not match:
        await update.message.reply_text("❌ Invalid Instagram link!")
        return

    await update.message.reply_text("⏳ Processing your request...")

    async with limiter:  # Enforce rate limit
        async with download_lock:
            download_queue.append((link, user_id))

# step 3

import logging
import traceback

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def error_handler(update: object, context: CallbackContext) -> None:
    """Handles unexpected errors in the bot."""
    logging.error(f"Exception occurred: {traceback.format_exc()}")

    # Inform the user about the error
    if update and isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ An unexpected error occurred. Please try again later."
        )

# Add error handler to the bot
application.add_error_handler(error_handler)

#step 4

from telegram.ext import BaseHandler
import time
import asyncio

# Dictionary to track user request timestamps
user_request_times = {}

async def rate_limit(update: Update, context: CallbackContext):
    """Limits the number of requests a user can send within a given timeframe."""
    user_id = update.effective_user.id
    current_time = time.time()

    # Allow one request every 5 seconds
    if user_id in user_request_times and (current_time - user_request_times[user_id]) < 5:
        await update.message.reply_text("⏳ Please wait before sending another request.")
        return

    # Update last request time
    user_request_times[user_id] = current_time

# Middleware-like function to apply rate limiting before executing a command
class RateLimitedHandler(BaseHandler):
    async def check_update(self, update: Update) -> bool:
        return True  # This allows all updates to be checked

    async def handle_update(self, update: Update, application: Application, check_result) -> None:
        await rate_limit(update, application)  # Apply rate limiting
        await super().handle_update(update, application, check_result)

# Apply rate limiting to all message handlers
application.add_handler(RateLimitedHandler())

#step 5
import sqlite3
import os

# Initialize database connection
DB_FILE = "bot_data.db"

def init_db():
    """Creates the database and tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS download_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            link TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

async def add_to_queue(user_id, link):
    """Adds a download request to the queue."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO download_queue (user_id, link) VALUES (?, ?)", (user_id, link))
    conn.commit()
    conn.close()

async def get_next_download():
    """Retrieves the next pending download request."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, link FROM download_queue WHERE status='pending' ORDER BY id ASC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result  # Returns (id, user_id, link) or None if empty

async def mark_download_complete(download_id):
    """Marks a download as completed in the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE download_queue SET status='completed' WHERE id=?", (download_id,))
    conn.commit()
    conn.close()

# step 6
import asyncio

async def process_download_queue(context: CallbackContext):
    """Continuously processes the download queue."""
    while True:
        download = await get_next_download()  # Fetch next pending download
        if not download:
            await asyncio.sleep(5)  # No pending downloads, wait and retry
            continue

        download_id, user_id, link = download

        # Notify user about download start
        message = await context.bot.send_message(
            chat_id=user_id, text="⏳ Downloading your media..."
        )

        try:
            # Download the media
            file_path = await download_instagram_media(link)

            # Progress tracking (update message)
            for progress in range(0, 101, 10):
                await asyncio.sleep(1)  # Simulating download progress
                try:
                    await message.edit_text(f"📥 Downloading: {progress}%")
                except Exception:
                    pass  # Ignore message edit failures

            # Send media file to user
            with open(file_path, "rb") as file:
                await context.bot.send_video(user_id, file) if file_path.endswith(".mp4") else await context.bot.send_photo(user_id, file)

            # Mark download as complete
            await mark_download_complete(download_id)

            # Delete downloaded file to save space
            os.remove(file_path)

            # Notify user
            await message.edit_text("✅ Download complete!")
        
        except Exception as e:
            logging.error(f"Download error: {e}")
            await message.edit_text("❌ Failed to download media.")
        
        await asyncio.sleep(2)  # Small delay before next download

# step 7 

import logging
import traceback

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def error_handler(update: object, context: CallbackContext) -> None:
    """Handles all errors and logs them."""
    logging.error(f"Exception: {context.error}")
    
    # Get full error traceback for debugging
    error_trace = traceback.format_exc()
    logging.error(f"Detailed Traceback:\n{error_trace}")

    # Notify the user about the error
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ An error occurred while processing your request. Please try again later."
        )

# 
from collections import defaultdict
import time

# Store user request timestamps
user_last_request = defaultdict(lambda: 0)

async def rate_limiter(update: Update, context: CallbackContext):
    """Limits the number of requests a user can make within a time frame."""
    user_id = update.effective_user.id
    current_time = time.time()
    
    # Define rate limit (e.g., one request every 5 seconds)
    cooldown = 5  
    if current_time - user_last_request[user_id] < cooldown:
        await update.message.reply_text("⏳ Please wait a few seconds before making another request.")
        return False
    
    # Update last request time
    user_last_request[user_id] = current_time
    return True

async def limited_download(update: Update, context: CallbackContext):
    """Wrapper function to enforce rate limiting on downloads."""
    if await rate_limiter(update, context):
        await download_media(update, context)  # Proceed with the actual download function

# step 8
import sqlite3

# Initialize SQLite Database
conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()

# Create table for download queue
cursor.execute('''
CREATE TABLE IF NOT EXISTS download_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    link TEXT,
    status TEXT DEFAULT 'pending'
)
''')
conn.commit()

async def add_to_queue(user_id, link):
    """Adds a download request to the persistent queue."""
    cursor.execute("INSERT INTO download_queue (user_id, link) VALUES (?, ?)", (user_id, link))
    conn.commit()

async def get_next_download():
    """Fetches the next pending download from the queue."""
    cursor.execute("SELECT id, user_id, link FROM download_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    if row:
        return {"id": row[0], "user_id": row[1], "link": row[2]}
    return None

async def mark_download_complete(download_id):
    """Marks a download as completed."""
    cursor.execute("UPDATE download_queue SET status = 'completed' WHERE id = ?", (download_id,))
    conn.commit()

#step 10
import logging
import traceback

# Configure logging
logging.basicConfig(
    filename="bot_errors.log",  # Log errors to a file
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def handle_error(update: object, context: CallbackContext) -> None:
    """Handles all unexpected errors and logs them."""
    error_message = f"Exception: {context.error}\nTraceback:\n{traceback.format_exc()}"
    logging.error(error_message)

    # Notify admins about the error (Replace 'ADMIN_CHAT_ID' with the actual ID)
    ADMIN_CHAT_ID = 123456789  # Change to your Telegram ID
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="⚠️ Bot encountered an error! Check logs.")

    # Send a user-friendly message
    if update and update.effective_chat:
        await update.effective_chat.send_message("⚠️ Oops! Something went wrong. The issue has been reported.")

#step 11
from telegram.ext import BaseFilter
import time

# Anti-Spam Mechanism
user_requests = {}

class RateLimitFilter(BaseFilter):
    """Prevents users from spamming requests within a short time."""
    def filter(self, message):
        user_id = message.from_user.id
        current_time = time.time()

        # Allow first request
        if user_id not in user_requests:
            user_requests[user_id] = current_time
            return True

        # Check if request is too soon
        last_request_time = user_requests[user_id]
        if current_time - last_request_time < 5:  # 5 seconds cooldown
            return False  # Ignore message
        else:
            user_requests[user_id] = current_time
            return True

rate_limiter = RateLimitFilter()

# Apply the rate limit filter
application.add_handler(MessageHandler(filters.TEXT & rate_limiter, download_media))

# Block Unauthorized Users (Example)
AUTHORIZED_USERS = {123456789, 987654321}  # Replace with real Telegram IDs

async def check_authorization(update: Update, context: CallbackContext):
    """Restricts access to only authorized users."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return False
    return True

#step 12
import logging
import traceback

# Configure Logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filename="bot_logs.log",  # Save logs to a file
)

async def error_handler(update: object, context: CallbackContext):
    """Handles unexpected errors and logs them."""
    logging.error(f"Exception occurred: {context.error}")
    logging.error(traceback.format_exc())  # Logs full error traceback

    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ An unexpected error occurred. Please try again later!")

# Apply the error handler
application.add_error_handler(error_handler)

#step 13

# --- Section 13: Admin Features & Analytics ---

# Define authorized admin IDs (update with your actual admin Telegram IDs)
AUTHORIZED_ADMINS = {123456789}  # Replace with your Telegram ID(s)

# Example: A global counter to track total downloads processed.
# In a real-world scenario, you'd record this in your persistent storage.
total_downloads = 0

async def stats(update: Update, context: CallbackContext):
    """Admin command to show total downloads processed."""
    global total_downloads
    user_id = update.effective_user.id

    if user_id not in AUTHORIZED_ADMINS:
        await update.message.reply_text("❌ You are not authorized to view stats.")
        return

    await update.message.reply_text(f"📊 Total downloads processed: {total_downloads}")

# Example function to increment total downloads.
# Call this in your download process (e.g., at the end of a successful download).
def increment_download_count():
    global total_downloads
    total_downloads += 1

# --- End of Section 13 ---

