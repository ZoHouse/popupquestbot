import os
import logging
import base64
import io
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
import supabase
from dotenv import load_dotenv
import re
from urllib.parse import urlparse
import time
import sys
import json
import pytz
import random
import asyncio
import uuid
import requests
import telegram
import queue # Import queue module
from PIL import Image

# Import our utility modules
import db_utils
from db_utils import (
    set_supabase_client, fetch_user, create_user, update_user,
    fetch_quest, fetch_active_quests, create_submission,
    fetch_submissions_by_user, update_submission, update_submission_status
)
import quest_utils
import badge_utils

# Import badge generator modules
try:
    import badge_generator
    import icon_provider
except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.error(f"Failed to import badge_generator: {e}")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Check essential environment variables
essential_vars = ["SUPABASE_URL", "SUPABASE_KEY", "TELEGRAM_BOT_TOKEN", "ADMIN_GROUP_ID", "PUBLIC_GROUP_ID"]
missing_vars = [var for var in essential_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing essential environment variables: {', '.join(missing_vars)}")
    sys.exit(1)
else:
    logger.info("All essential environment variables seem to be present.")

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase_client = None # Initialize as None

try:
    logger.info("Attempting to initialize Supabase client...")
    supabase_client = supabase.create_client(supabase_url, supabase_key)
    logger.info("Supabase client initialized successfully.")

    # Pass Supabase client to badge_generator and db_utils
    try:
        badge_generator.set_supabase_client(supabase_client, supabase_url)
        logger.info("Passed Supabase client to badge_generator.")
        
        # Initialize db_utils with the supabase client
        db_utils.set_supabase_client(supabase_client)
        logger.info("Passed Supabase client to db_utils.")
    except Exception as e:
        logger.error(f"Failed to set Supabase client in modules: {e}")
        # Depending on severity, might want to exit: sys.exit(1)

except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    sys.exit(1)

# Before setup, check database schema
try:
    # Get a single row to understand the schema
    schema_info = supabase_client.table('quests').select('*').limit(1).execute()
    
    if schema_info.data:
        available_columns = set(schema_info.data[0].keys())
        logger.info(f"Available columns in quests table: {available_columns}")
        # Print the exact response to debug the schema
        logger.info(f"Schema info data: {schema_info.data}")
    else:
        # If no data, try to get column info from an empty result
        logger.info("No data in quests table, using default column set")
        available_columns = {'id', 'title', 'description', 'validation_type', 'points', 'deadline', 'keyword', 'active'}
    
    # Define key columns that must exist
    required_columns = {'id', 'title', 'description', 'validation_type', 'points', 'deadline', 'keyword'}
    
    # Check if all required columns exist
    missing_columns = required_columns - available_columns
    if missing_columns:
        logger.error(f"Missing required columns in quests table: {missing_columns}")
    
    # Check if category_type is in the schema
    if 'category_type' in available_columns:
        logger.info("category_type column exists in schema")
    else:
        logger.warning("category_type column missing from schema but needed for constraint")
        
    logger.info("Database schema check completed")
except Exception as e:
    logger.error(f"Error checking database schema: {e}")
    logger.info("Continuing with default schema assumptions")
    available_columns = {'id', 'title', 'description', 'validation_type', 'points', 'deadline', 'keyword', 'active'}

# Bot configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")
PUBLIC_GROUP_ID = os.getenv("PUBLIC_GROUP_ID")

# Determine webhook settings - default to webhook mode on Render
is_on_render = os.environ.get("RENDER", "").lower() == "true"
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "true" if is_on_render else "false").lower() == "true"
PORT = int(os.getenv("PORT", "10000"))  # Use Render's port

# Default webhook URL based on render service name if available
default_webhook_url = None
render_service_name = os.environ.get("RENDER_SERVICE_NAME", "")
if render_service_name:
    default_webhook_url = f"https://{render_service_name}.onrender.com"
    logger.info(f"Using default webhook URL based on RENDER_SERVICE_NAME: {default_webhook_url}")

# Set webhook URL with proper validation
WEBHOOK_URL = os.getenv("WEBHOOK_URL", default_webhook_url)
if USE_WEBHOOK:
    if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://"):
        logger.critical(f"CRITICAL ERROR: WEBHOOK_URL environment variable is missing, empty, or invalid (must start with https://). Value: '{WEBHOOK_URL}'")
        logger.critical(f"Please set a valid WEBHOOK_URL in your environment variables.")
        logger.critical(f"If running on Render, it should be: https://YOUR-SERVICE-NAME.onrender.com")
        sys.exit(1)
    else:
        logger.info(f"WEBHOOK_URL successfully read: {WEBHOOK_URL}")

logger.info("Bot configuration variables loaded.")

# Quest points presets
POINT_VALUES = [111, 210, 300, 420, 690, 766]

# Quest categories
PARTY_NAMES = ["Zo Trip", "FIFA", "Poker", "Founders Connect"]
CATEGORY_TYPES = {
    "Zo Trip": ["Zo 🌌✨ Zo 🌠 | The Initiate Path", "Daily Check-in ✅", "Event-Specific 🎭"],
    "FIFA": ["FIFA Champion 🏆", "FIFA Achievements 🎮", "First Timer 🆕"],
    "Poker": ["Poker Pro 🃏", "Poker Achievements 🎲", "First Timer 🆕"],
    "Founders Connect": ["Networking 🤝", "Special Events 🎉", "Activities 🏄‍♂️"]
}


# Add a webhook mode-specific chat ID handler function
def get_normalized_chat_id(chat_id):
    '''Helper function to normalize chat ID format for webhook and polling modes.'''
    # Convert to string for consistent comparison
    chat_id_str = str(chat_id)
    
    # Log the raw chat ID
    logger.info(f"Raw chat_id: {chat_id} (type: {type(chat_id)})")
    
    # Try multiple formats
    formats = [
        chat_id_str,                   # Original format
        chat_id_str.replace('-', ''),  # No hyphen
        chat_id_str.lstrip('-'),       # Just digits
        f"-{chat_id_str.lstrip('-')}"  # Ensure hyphen prefix
    ]
    
    logger.info(f"Normalized chat ID formats: {formats}")
    return formats

# User session data for multi-step commands
user_sessions = {}

# Conversation states for wallet collection
WALLET_ADDRESS = 1
QUEST_DETAIL = 2

# Store quests displayed to users
user_displayed_quests = {}  # Format: {user_id: {quest_number: quest_id}}

# Pagination settings
QUESTS_PER_PAGE = 3  # Changed from 5 to 3 quests per page
ITEMS_PER_PAGE = 4  # Number of items (parties/categories) per page

# EVM wallet address regex pattern (0x followed by 40 hex characters)
EVM_WALLET_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')

# Function to upload image to Supabase storage
async def upload_image_to_supabase(image_buffer, content_type="image/png"):
    """
    Upload an image to Supabase storage from a memory buffer
    
    Args:
        image_buffer: BytesIO buffer containing image data
        content_type: The content type of the image (default: "image/png")
        
    Returns:
        The public URL of the uploaded image or None if upload failed
    """
    try:
        # Generate a unique filename based on timestamp
        filename = f"quest_image_{int(time.time())}.png"
        
        logging.info("Uploading image from memory buffer to Supabase")
        file_bytes = image_buffer.getvalue() if hasattr(image_buffer, 'getvalue') else image_buffer
        
        # Upload to Supabase storage
        response = supabase_client.storage.from_("quest_images").upload(
            file=file_bytes,
            path=filename,
            file_options={"content-type": content_type}
        )
        
        # Check Supabase response structure
        logger.info(f"Supabase upload raw response: {response}") # Log raw response for debugging
        # Assuming response indicates success if no exception is raised and status code is ok (though storage client might not provide status directly)

        # Get the public URL
        logger.info(f"Attempting to get public URL for path: {filename}")
        public_url_response = supabase_client.storage.from_("quest_images").get_public_url(filename)
        logger.info(f"Supabase get_public_url raw response: {public_url_response}")

        # Extract the URL string correctly based on actual response structure
        # Adjust this based on the logged response structure
        image_url = public_url_response # Assuming the response IS the URL string directly
        if not isinstance(image_url, str) or not image_url.startswith('http'):
             logger.error(f"Failed to extract valid public URL from Supabase response: {public_url_response}")
             return None

        logger.info(f"Image uploaded successfully: {image_url}")
        return image_url
    except Exception as e:
        logger.error(f"Error uploading image to Supabase: {e}")
        # Log specific Supabase errors if available
        if hasattr(e, 'details'):
             logger.error(f"Supabase error details: {e.details}")
        if hasattr(e, 'message'):
             logger.error(f"Supabase error message: {e.message}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if this is a private chat (DM)
    if update.effective_chat.type == "private":
        # Check if user already exists in database
        user = supabase_client.table("users").select("*").eq("id", user_id).execute()
        
        if not user.data:
            # Create user if not exists
            user_data = {
                "id": user_id,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "last_name": update.effective_user.last_name,
                "total_points": 0,
                "joined_at": datetime.now().isoformat()
            }
            supabase_client.table("users").insert(user_data).execute()
            
            # Ask for wallet address - First time visitor
            await update.message.reply_text(
                "Zo Zo Trippers, \n\n"
                "I'm DXBxZo's Quest bot. Please provide your EVM wallet address so i can start airdroping you goodness."
            )
            return WALLET_ADDRESS
        
        # Check if wallet address is already set
        elif not user.data[0].get("wallet_address"):
            # Ask for wallet address - Repeat visitor without wallet
            await update.message.reply_text(
                "Zo Zo, Welcome back\n\n"
                "Please provide your EVM wallet address so i can start airdroping you goodness."
            )
            return WALLET_ADDRESS
        
        # User exists and has wallet
        else:
            wallet = user.data[0].get("wallet_address", "Not set")
            wallet_display = f"{wallet[:6]}...{wallet[-4:]}" if wallet.startswith("0x") else wallet
            
            await update.message.reply_text(
                f"Welcome back tripper,\n\n"
                f"Your registered wallet: {wallet_display}\n\n"
                f"Join the [DXBxZo Live](https://t.me/+wfDEVgQSsa8wZjVl) to share vibes and finish quests to earn points.\n\n"
                f"Try Commands:\n"
                f"/viewquests - See available quests\n"
                f"/leaderboard - View top participants\n"
                f"/updatewallet - Change your wallet address",
                parse_mode="Markdown"
            )
    else:
        # Regular group response
        await update.message.reply_text(
            "Zo Zo Zo Trippers, \n\n"
            "Join the [DXBxZo Live](https://t.me/+wfDEVgQSsa8wZjVl) to share vibes and finish quests to earn points. \n\n"
            "Try Commands \n"
            "/viewquests\n"
            "/leaderboard",
            parse_mode="Markdown"
        )
    
    return ConversationHandler.END

async def collect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet address collection"""
    user_id = update.effective_user.id
    wallet_address = update.message.text.strip()
    
    # Debug logging
    logger.info(f"Received wallet address: '{wallet_address}' with length {len(wallet_address)}")
    
    # Clean the address - remove any non-alphanumeric characters except the 0x prefix
    if wallet_address.lower().startswith('0x'):
        cleaned_address = '0x' + ''.join([c for c in wallet_address[2:] if c.isalnum()])
    else:
        cleaned_address = '0x' + ''.join([c for c in wallet_address if c.isalnum()])
    
    logger.info(f"Cleaned address: '{cleaned_address}' with length {len(cleaned_address)}")
    logger.info(f"Validation result: {bool(EVM_WALLET_PATTERN.match(cleaned_address))}")
    
    # Validate wallet address format
    if not EVM_WALLET_PATTERN.match(cleaned_address):
        await update.message.reply_text(
            "❌ Invalid wallet address format. Please provide a valid EVM wallet address.\n"
            "It should start with '0x' followed by 40 hexadecimal characters."
        )
        return WALLET_ADDRESS
    
    # Store wallet address in database
    try:
        logger.info(f"Attempting to save wallet address for user {user_id}")
        
        # Log the SQL query that would be executed
        logger.info(f"Supabase query: UPDATE users SET wallet_address = '{cleaned_address}' WHERE id = {user_id}")
        
        # Try to get the user first to verify the table exists and is accessible
        check_user = supabase_client.table("users").select("*").eq("id", user_id).execute()
        logger.info(f"User check result: {check_user}")
        
        # Now attempt the update
        result = supabase_client.table("users").update({"wallet_address": cleaned_address}).eq("id", user_id).execute()
        logger.info(f"Supabase update result: {result}")
        
        # Success message
        wallet_display = f"{cleaned_address[:6]}...{cleaned_address[-4:]}"
        await update.message.reply_text(
            f"✅ Wallet address {wallet_display} has been successfully saved!\n\n"
            f"Join the [DXBxZo Live](https://t.me/+wfDEVgQSsa8wZjVl) to share vibes and finish quests to earn points.\n\n"
            f"Try Commands:\n"
            f"/viewquests - See available quests\n"
            f"/leaderboard - View top participants\n"
            f"/updatewallet - Change your wallet address",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error saving wallet address: {e}")
        logger.error(f"Error details: {repr(e)}")
        
        # Detailed error information for debugging
        if hasattr(e, 'response'):
            try:
                logger.error(f"Response details: {e.response.text}")
            except:
                logger.error("Could not extract response text from error")
                
        # More detailed error message for debugging
        await update.message.reply_text(
            f"❌ An error occurred while saving your wallet address: {str(e)}\n"
            f"Please try again later or contact support."
        )
    
    return ConversationHandler.END

async def update_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /updatewallet command."""
    chat_type = update.effective_chat.type
    
    # Only allow in private chats
    if chat_type != "private":
        await update.message.reply_text("Please use this command in a private chat with the bot.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Please provide your new EVM wallet address (starting with 0x)."
    )
    
    return WALLET_ADDRESS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def new_quest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the quest creation process."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id    # Ensure command is used in admin group
    chat_id = update.effective_chat.id
    chat_formats = get_normalized_chat_id(chat_id)
    admin_formats = get_normalized_chat_id(ADMIN_GROUP_ID)
    
    logger.info(f"Chat: {chat_id}, Admin: {ADMIN_GROUP_ID}")
    
    # Check if any chat format matches any admin format
    is_admin = any(cf in admin_formats for cf in chat_formats)
    
    if not is_admin:
        logger.warning(f"Admin check failed: chat_id={chat_id}, ADMIN_GROUP_ID={ADMIN_GROUP_ID}")
        await update.message.reply_text("This command can only be used in the admin group.")
        return

        await update.message.reply_text("This command can only be used in the admin group.")
        return
    
    # Initialize session for this user
    user_sessions[user_id] = {
        "state": "awaiting_title",
        "quest_data": {},
        "pagination": {
            "party_page": 1,
            "category_page": 1
        }
    }
    
    await update.message.reply_text("Let's create a new quest! Please provide a title:")

async def view_quests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display available quests with pagination."""
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        logger.info(f"Received /viewquests command from chat_id: {chat_id}")
        
        # Get page number from context or default to 1
        page = context.user_data.get('quest_page', 1)
        
        try:
            # Get all active quests
            query = supabase_client.table("quests").select("*")
            if 'active' in available_columns:
                query = query.eq("active", True)
            quests = query.execute()
            logger.info(f"Fetched {len(quests.data) if quests.data else 0} active quests")
                
        except Exception as e:
            logger.error(f"Error fetching quests from Supabase: {e}")
            await update.message.reply_text("Error: Could not fetch quests from the database. Please try again later.")
            return
        
        if not quests.data:
            logger.info("No quests found")
            await update.message.reply_text("No quests found.")
            return
        
        # Get current date in ISO format
        today = datetime.now().date().isoformat()
        
        # Separate future and everyday quests
        future_quests = [q for q in quests.data if q.get("deadline") != "everyday" and q.get("deadline", "") >= today]
        everyday_quests = [q for q in quests.data if q.get("deadline") == "everyday"]
        
        # Sort future quests by deadline
        future_quests.sort(key=lambda x: x.get("deadline", "9999-99-99"))
        
        # Combine lists with future quests first, then everyday quests
        all_quests = future_quests + everyday_quests
        
        # Calculate total pages
        total_quests = len(all_quests)
        total_pages = (total_quests + QUESTS_PER_PAGE - 1) // QUESTS_PER_PAGE  # Ceiling division
        
        # Adjust page if it's out of range
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # Save current page
        context.user_data['quest_page'] = page
        
        # Calculate start and end indices for this page
        start_idx = (page - 1) * QUESTS_PER_PAGE
        end_idx = min(start_idx + QUESTS_PER_PAGE, total_quests)
        
        # Get quests for current page
        page_quests = all_quests[start_idx:end_idx]
        
        # Reset the displayed quests mapping for this user
        user_displayed_quests[user_id] = {}
        
        # Format and send quest information
        message = f"📝 AVAILABLE QUESTS 📝\n\n"
        
        for i, quest in enumerate(page_quests, 1):
            # Add to displayed quests map
            user_displayed_quests[user_id][i] = quest["id"]
            
            # Get deadline
            deadline = quest.get("deadline", "N/A")
            
            # Get points
            points = quest.get("points", "---")
            
            # Show title, points and deadline
            message += f"{i}. {quest.get('title', 'No title')}\n"
            message += f"   {points} pts - {deadline}\n\n"
        
        # Add instruction
        message += "Reply with a number to see quest details\n"
        
        # Create navigation buttons
        keyboard = []
        nav_row = []
        
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️", callback_data=f"questpage_{page-1}"))
        
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("▶️", callback_data=f"questpage_{page+1}"))
        
        if nav_row:
            keyboard.append(nav_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        # Log the user's displayed quests mapping for debugging
        logger.info(f"User {user_id} displayed quests mapping: {user_displayed_quests[user_id]}")
        
        try:
            await update.message.reply_text(message, reply_markup=reply_markup)
            
            # Setup conversation state to accept quest number
            logger.info(f"Setting conversation state to QUEST_DETAIL for user {user_id}")
            return QUEST_DETAIL
            
        except Exception as e:
            logger.error(f"Error sending viewquests response: {e}")
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Unexpected error in view_quests: {e}")
        try:
            await update.message.reply_text("An unexpected error occurred. Please try again later.")
        except:
            logger.error("Could not send error message to user")
        return ConversationHandler.END

async def handle_quest_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination callback for quests."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Extract page number from callback data
    page = int(query.data.split("_")[1])
    logger.info(f"Pagination callback: user {user_id} requested page {page}")
    
    # Store the page in user_data
    context.user_data['quest_page'] = page
    
    try:
        # Get all active quests
        query = supabase_client.table("quests").select("*")
        if 'active' in available_columns:
            query = query.eq("active", True)
        quests = query.execute()
    except Exception as e:
        logger.error(f"Error fetching quests for pagination: {e}")
        await query.answer("Error fetching quests")
        return
    
    # Get current date in ISO format
    today = datetime.now().date().isoformat()
    
    # Separate future and everyday quests
    future_quests = [q for q in quests.data if q.get("deadline") != "everyday" and q.get("deadline", "") >= today]
    everyday_quests = [q for q in quests.data if q.get("deadline") == "everyday"]
    
    # Sort future quests by deadline
    future_quests.sort(key=lambda x: x.get("deadline", "9999-99-99"))
    
    # Combine lists with future quests first, then everyday quests
    all_quests = future_quests + everyday_quests
    
    # Calculate total pages
    total_quests = len(all_quests)
    total_pages = (total_quests + QUESTS_PER_PAGE - 1) // QUESTS_PER_PAGE  # Ceiling division
    
    # Adjust page if it's out of range
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    # Calculate start and end indices for this page
    start_idx = (page - 1) * QUESTS_PER_PAGE
    end_idx = min(start_idx + QUESTS_PER_PAGE, total_quests)
    
    # Get quests for current page
    page_quests = all_quests[start_idx:end_idx]
    
    # Reset the displayed quests mapping for this user
    user_displayed_quests[user_id] = {}
    
    # Format quest information
    message = f"📝 AVAILABLE QUESTS 📝\n\n"
    
    for i, quest in enumerate(page_quests, 1):
        # Add to displayed quests map
        user_displayed_quests[user_id][i] = quest["id"]
        
        # Get deadline
        deadline = quest.get("deadline", "N/A")
        
        # Get points
        points = quest.get("points", "---")
        
        # Show title, points and deadline
        message += f"{i}. {quest.get('title', 'No title')}\n"
        message += f"   {points} pts - {deadline}\n\n"
    
    # Add instruction
    message += "Reply with a number to see quest details\n"
    
    # Create navigation buttons
    keyboard = []
    nav_row = []
    
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"questpage_{page-1}"))
    
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"questpage_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    # Edit message with new quests
    try:
        await query.edit_message_text(message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error updating pagination message: {e}")
        await query.answer("Error updating the message")

async def show_quest_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display details for a selected quest."""
    user_id = update.effective_user.id
    
    try:
        # Get quest number from message text
        message_text = update.message.text.strip()
        logger.info(f"Received quest detail request: '{message_text}' from user {user_id}")
        
        try:
            quest_number = int(message_text)
            logger.info(f"Parsed quest number: {quest_number}")
        except ValueError:
            # Not a number, ignore
            logger.info(f"Invalid quest number format: {message_text}")
            return ConversationHandler.END
        
        # Check if the number is valid
        if quest_number not in user_displayed_quests[user_id]:
            logger.warning(f"Quest number {quest_number} not found in user's displayed quests")
            await update.message.reply_text(
                "Invalid quest number. Please use /viewquests and select a valid number."
            )
            return ConversationHandler.END
        
        # Get the quest ID
        quest_id = user_displayed_quests[user_id][quest_number]
        logger.info(f"Looking up quest ID: {quest_id}")
        
        # Fetch quest details
        quest_result = supabase_client.table("quests").select("*").eq("id", quest_id).execute()
        
        if not quest_result.data:
            logger.warning(f"Quest ID {quest_id} not found in database")
            await update.message.reply_text("Quest not found. It may have been deleted.")
            return ConversationHandler.END
            
        quest = quest_result.data[0]
        logger.info(f"Retrieved quest: {quest['title']} (ID: {quest_id})")
        
        # Format quest details
        detail_message = (
            f"🔍 QUEST DETAILS 🔍\n\n"
            f"📌 Title: {quest.get('title', 'No title')}\n\n"
            f"📝 Description: {quest.get('description', 'No description')}\n\n"
        )
        
        # Add optional party if available
        if quest.get('party_name'):
            detail_message += f"🎪 Party: {quest.get('party_name')}\n\n"
        
        detail_message += (
            f"🏆 Points: {quest.get('points', 'N/A')}\n\n"
            f"⏱️ Deadline: {quest.get('deadline', 'N/A')}\n\n"
            f"📸 Validation: {quest.get('validation_type', 'N/A')}\n\n"
            f"🔑 Keyword: {quest.get('keyword', 'N/A')}\n\n"
            f"To complete this quest, post a {quest.get('validation_type', '').lower()} "
            f"with the keyword '{quest.get('keyword', '')}' in the caption."
        )
        
        # First try to get badge image from badge_images table
        # Ensure quest_id is properly formatted - it might be an integer or UUID
        logger.info(f"Attempting to fetch badge image for quest ID: {quest_id}")
        try:
            # Try both raw ID and string conversion
            logger.info(f"Querying badge_images with quest_id as string: {str(quest_id)}")
            # Remove await since execute() returns the result directly, not a coroutine
            badge_image = supabase_client.table("badge_images").select("image_data").eq("quest_id", str(quest_id)).execute()
            
            # If no results, try without string conversion
            if not badge_image.data or len(badge_image.data) == 0:
                logger.info(f"No results with string conversion, trying with raw quest_id: {quest_id}")
                badge_image = supabase_client.table("badge_images").select("image_data").eq("quest_id", quest_id).execute()
            
            if badge_image.data and len(badge_image.data) > 0:
                logger.info(f"Badge image found in database for quest {quest_id}")
                
                if badge_image.data[0].get("image_data"):
                    logger.info(f"Badge image has data, size: {len(badge_image.data[0]['image_data'])}")
                    # Decode base64 image data and convert to bytes
                    img_data = base64.b64decode(badge_image.data[0]["image_data"])
                    logger.info(f"Decoded base64 data, size: {len(img_data)} bytes")
                    
                    img_buffer = io.BytesIO(img_data)
                    img_buffer.seek(0)
                    
                    # Send the badge image with quest details as caption
                    logger.info(f"Sending photo with badge image for quest {quest_id}")
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=img_buffer,
                        caption=detail_message
                    )
                    logger.info(f"Successfully sent quest details for {quest_id} with badge from database")
                    return ConversationHandler.END
                else:
                    logger.warning(f"Badge image record found but contains no image data for quest {quest_id}")
            else:
                logger.warning(f"No badge image found in database for quest {quest_id}")
        except Exception as e:
            logger.error(f"Error retrieving badge image from database: {e}")
            # Continue to fallback options
        
        # Check if quest has an image (fallback to image_file_id)
        image_file_id = quest.get('image_file_id')
        
        if image_file_id:
            logger.info(f"Falling back to image_file_id: {image_file_id}")
            try:
                # Send the image with quest details as caption
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=image_file_id,
                    caption=detail_message
                )
                logger.info(f"Successfully sent quest details with image_file_id")
            except Exception as e:
                logger.error(f"Error sending quest image: {e}")
                # Fall back to text-only if image fails
                logger.info("Falling back to text-only message")
                await update.message.reply_text(detail_message)
        else:
            # No image, send text only
            logger.info(f"No images available for quest {quest_id}, sending text-only response")
            await update.message.reply_text(detail_message)
        
    except ValueError:
        # Not a number, ignore
        pass
    except Exception as e:
        logger.error(f"Unexpected error in show_quest_detail: {str(e)}")
    
    return ConversationHandler.END

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the top 10 users on the leaderboard."""
    try:
        logger.info(f"Received /leaderboard command from chat_id: {update.effective_chat.id}")
        
        try:
            # Get all approved submissions using db_utils
            submissions = db_utils.fetch_approved_submissions()
            
            if not submissions:
                logger.info("No approved submissions found")
                await update.message.reply_text("No users on the leaderboard yet. Complete quests to earn points!")
                return
            
            # Get all quests for point lookup
            all_quests = []
            quests_result = db_utils.safe_supabase_call(
                lambda: db_utils.supabase_client.table("quests").select("id,title,points").execute(),
                fallback_value={"data": []}
            )
            if quests_result and quests_result.data:
                all_quests = quests_result.data
            
            quest_points = {quest["id"]: quest["points"] for quest in all_quests}
            quest_titles = {quest["id"]: quest["title"] for quest in all_quests}
            
            # Calculate points by user
            user_points = {}
            user_completed_quests = {}
            user_ids = set()
            
            for submission in submissions:
                user_id = submission["user_id"]
                quest_id = submission["quest_id"]
                user_ids.add(user_id)
                
                # Skip if quest doesn't exist or has no points value
                if quest_id not in quest_points:
                    continue
                
                # Initialize user data if not exists
                if user_id not in user_points:
                    user_points[user_id] = 0
                    user_completed_quests[user_id] = []
                
                # Add quest points to user total
                points = quest_points[quest_id]
                user_points[user_id] += points
                
                # Track completed quest details
                user_completed_quests[user_id].append({
                    "quest_id": quest_id,
                    "title": quest_titles.get(quest_id, "Unknown Quest"),
                    "points": points,
                    "submitted_at": submission.get("submitted_at")
                })
            
            # Get user profiles for those with approved submissions
            users_data = {}
            if user_ids:
                # Fetch users in batches to avoid large queries
                for i in range(0, len(user_ids), 50):
                    user_ids_batch = list(user_ids)[i:i+50]
                    for user_id in user_ids_batch:
                        user = db_utils.fetch_user(user_id)
                        if user:
                            users_data[user_id] = user
            else:
                await update.message.reply_text("No users on the leaderboard yet. Complete quests to earn points!")
                return
            
            # Create leaderboard entries
            leaderboard_entries = []
            for user_id, points in user_points.items():
                if user_id in users_data:
                    user = users_data[user_id]
                    username = user.get("username") or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    if not username:
                        username = f"User {user_id}"
                    
                    leaderboard_entries.append({
                        "user_id": user_id,
                        "username": username,
                        "points": points,
                        "quests_completed": len(user_completed_quests.get(user_id, []))
                    })
            
            # Sort by points (descending)
            sorted_users = sorted(leaderboard_entries, key=lambda x: x["points"], reverse=True)
            
            # Take top 10
            top_users = sorted_users[:10]
            
            if not top_users:
                await update.message.reply_text("No users on the leaderboard yet. Complete quests to earn points!")
                return
            
            message = "🏆 LEADERBOARD 🏆\n\n"
            for i, user in enumerate(top_users, 1):
                message += f"{i}. {user['username']}: {user['points']} points ({user['quests_completed']} quests)\n"
            
            await update.message.reply_text(message)
            logger.info("Successfully sent leaderboard response")
            
        except Exception as e:
            logger.error(f"Error fetching leaderboard data: {e}")
            await update.message.reply_text("Error: Could not fetch leaderboard data. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in leaderboard: {e}")
        try:
            await update.message.reply_text("An unexpected error occurred. Please try again later.")
        except:
            logger.error("Could not send error message to user")

async def tripper_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display information about a specific user for admins."""
    chat_id = update.effective_chat.id
    
    # Ensure command is used in admin group
    if str(chat_id) != ADMIN_GROUP_ID:
        await update.message.reply_text("This command can only be used in the admin group.")
        return
    
    # Check if a user ID was provided
    if len(context.args) != 1:
        await update.message.reply_text("Please provide a user ID or username. Format: /tripper @username or /tripper user_id")
        return
    
    # Get the user identifier
    user_identifier = context.args[0]
    
    # If username is provided with @ symbol, remove it
    if user_identifier.startswith('@'):
        username = user_identifier[1:]
        # Find user by username
        try:
            user_result = supabase_client.table("users").select("*").eq("username", username).execute()
        except Exception as e:
            logger.error(f"Error querying user by username: {e}")
            await update.message.reply_text(f"Error retrieving user data: {str(e)}")
            return
    else:
        # Try to parse as user ID
        try:
            user_id = int(user_identifier)
            user_result = supabase_client.table("users").select("*").eq("id", user_id).execute()
        except ValueError:
            await update.message.reply_text("Invalid user ID. Please provide a valid numeric ID or username with @ symbol.")
            return
        except Exception as e:
            logger.error(f"Error querying user by ID: {e}")
            await update.message.reply_text(f"Error retrieving user data: {str(e)}")
            return
    
    # Check if user exists
    if not user_result.data:
        await update.message.reply_text("User not found. Please check the ID or username.")
        return
    
    user = user_result.data[0]
    user_id = user["id"]
    
    try:
        # Get all submissions by this user
        all_submissions = supabase_client.table("submissions").select("*").eq("user_id", user_id).execute()
        
        # Get approved submissions
        approved_submissions = supabase_client.table("submissions").select("*").eq("user_id", user_id).eq("status", "approved").execute()
        
        # Format user information
        username = user.get("username", "No username")
        total_points = user.get("total_points", 0)
        total_attempts = len(all_submissions.data) if all_submissions.data else 0
        completed_quests = len(approved_submissions.data) if approved_submissions.data else 0
        wallet = user.get("wallet_address", "Not set")
        
        # Format wallet for display if it exists
        wallet_display = f"{wallet[:6]}...{wallet[-4:]}" if wallet and wallet.startswith("0x") else wallet
        
        response = (
            f"📊 TRIPPER INFO 📊\n\n"
            f"User: @{username}\n"
            f"Telegram ID: {user_id}\n"
            f"Total Points: {total_points}\n"
            f"Number of Quests Attempted: {total_attempts}\n"
            f"Number of Quests Completed: {completed_quests}\n"
            f"Wallet: {wallet_display}"
        )
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Error retrieving submissions: {e}")
        await update.message.reply_text(f"Error retrieving submission data: {str(e)}")

def normalize_group_id(group_id):
    """
    Normalize group ID to a consistent format
    
    Args:
        group_id: Group ID that could be a string or an int
        
    Returns:
        Normalized string representation of the group ID
    """
    # Convert to string for consistent handling
    str_id = str(group_id)
    
    # Remove any prefix that Telegram might add
    for prefix in ['chat', 'supergroup']:
        if str_id.startswith(prefix):
            str_id = str_id[len(prefix):]
    
    # Ensure consistent handling of negative IDs (group IDs are usually negative)
    if str_id.startswith('-100'):
        # This is already in the canonical format
        pass
    elif str_id.startswith('-'):
        # Add the 100 prefix if it's missing 
        if not str_id.startswith('-100'):
            str_id = '-100' + str_id[1:]
    
    logger.info(f"Normalized group ID from {group_id} to {str_id}")
    return str_id

async def forward_submission_to_admin(context: ContextTypes.DEFAULT_TYPE, submission: dict, quest: dict, user: dict):
    """
    Forward a submission to the admin group for review
    
    Args:
        context: Context from Telegram
        submission: Submission data dictionary
        quest: Quest data dictionary
        user: User data dictionary
    
    Returns:
        bool: Whether the forwarding was successful
    """
    try:
        # Use the global ADMIN_GROUP_ID constant
        admin_group_id = ADMIN_GROUP_ID
        logger.info(f"Attempting to forward submission to admin group ID: {admin_group_id}")
        
        # Create approval buttons for admins
        buttons = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{submission['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{submission['id']}")
            ]
        ]
        admin_markup = InlineKeyboardMarkup(buttons)
        
        # Prepare the caption
        caption = (
            f"Submission for: {quest['title']} ({quest['keyword']})\n"
            f"User: {user['username'] or user['first_name']}\n"
            f"Points: {quest['points']}"
        )
        logger.info(f"Prepared submission caption: {caption}")
        
        # Send media to admin group
        media_type = submission.get('media_type')
        media_file_id = submission.get('media_file_id')
        
        if media_type == 'photo' and media_file_id:
            logger.info(f"Sending photo to admin group with file_id: {media_file_id}")
            admin_message = await context.bot.send_photo(
                chat_id=admin_group_id,
                photo=media_file_id,
                caption=caption,
                reply_markup=admin_markup
            )
        elif media_type == 'video' and media_file_id:
            # Check video file size (get file info first)
            file = await context.bot.get_file(media_file_id)
            file_size = getattr(file, 'file_size', 0)
            
            # Check if video is too large (20MB is a safer limit)
            if file_size and file_size > 20 * 1024 * 1024:
                logger.warning(f"Video file is large: {file_size/1024/1024:.2f}MB, might cause issues")
            
            logger.info(f"Sending video to admin group with file_id: {media_file_id}")
            admin_message = await context.bot.send_video(
                chat_id=admin_group_id,
                video=media_file_id,
                caption=caption,
                reply_markup=admin_markup
            )
        else:
            # No media found
            logger.error(f"Submission {submission['id']} has no valid media")
            admin_message = await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"⚠️ ERROR: Submission {submission['id']} has no valid media\n\n{caption}",
                reply_markup=admin_markup
            )
            
        if admin_message:
            logger.info(f"Successfully forwarded submission {submission['id']} to admin group, message_id: {admin_message.message_id}")
            
            # Update submission with admin_message_id
            update_submission(
                submission_id=submission['id'],
                admin_message_id=admin_message.message_id
            )
            
            return True
            
    except Exception as e:
        logger.exception(f"Error forwarding submission to admin: {e}")
        # Try to get more information about the error
        if hasattr(e, 'message'):
            logger.error(f"Error message: {e.message}")
        if hasattr(e, 'description'):
            logger.error(f"Error description: {e.description}")
    
    return False

# Update the handle_submission function to use the forward function
async def handle_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle photo/video submissions to quests
    
    Args:
        update: Update from Telegram
        context: CallbackContext from Telegram
    """
    # Only process submissions to the public group
    public_group_id = PUBLIC_GROUP_ID
    logger.info(f"Submission received, checking groups. PUBLIC_GROUP_ID={public_group_id}")
    
    # Log original IDs for debugging
    logger.info(f"Original IDs: chat={update.effective_chat.id}, public={public_group_id}")
    
    # Normalize both IDs for comparison
    norm_chat_id = normalize_group_id(update.effective_chat.id)
    norm_public_id = normalize_group_id(public_group_id)
    logger.info(f"Normalized IDs: chat={norm_chat_id}, public={norm_public_id}")
    
    # Try multiple comparison methods
    if norm_chat_id != norm_public_id and str(update.effective_chat.id) != str(public_group_id):
        logger.info(f"Submission not in public group. Got {update.effective_chat.id}, expected {public_group_id}")
        return
    
    logger.info(f"Handling submission in group {update.effective_chat.id}, compared to {public_group_id}")
    
    # Get message, file_id
    message = update.effective_message
    photo_file_id = None
    video_file_id = None
    
    # Check for media
    if message.photo:
        photo_file_id = message.photo[-1].file_id
        logger.info(f"Photo submission with file_id: {photo_file_id}")
    elif message.video:
        # Check video file size
        if message.video.file_size and message.video.file_size > 20 * 1024 * 1024:  # 20 MB
            await message.reply_text("⚠️ Video is too large. Please upload a video smaller than 20 MB.")
            return
        video_file_id = message.video.file_id
        logger.info(f"Video submission with file_id: {video_file_id}")
    else:
        # Not a media message
        logger.info("Message doesn't contain photo or video")
        return
    
    # Check for caption
    if not message.caption:
        await message.reply_text("⚠️ Please include the quest keyword (e.g., zozozo123) in your submission caption.")
        return
    
    # Look for keyword in caption
    caption = message.caption
    logger.info(f"Caption: {caption}")
    
    # Try multiple regex patterns to match keywords (only focus on standard format)
    keyword_patterns = [
        re.compile(r'zozozo\d+'),  # Standard format (e.g., zozozo123)
        re.compile(r'zozozo[\s_-]?\d+'),  # With possible separator (e.g., zozozo-123)
        re.compile(r'zo[\s_-]?zo[\s_-]?zo[\s_-]?\d+')  # With spaces between zo's (e.g., zo zo zo 123)
    ]
    
    # Try each pattern
    keyword_match = None
    matched_pattern = None
    
    for pattern in keyword_patterns:
        match = pattern.search(caption.lower())
        if match:
            keyword_match = match
            matched_pattern = pattern.pattern
            break
    
    if not keyword_match:
        logger.info(f"No keyword match found in caption: {caption}")
        await message.reply_text("⚠️ No matching quest found. Please include the correct quest keyword (e.g., zozozo123) in your submission caption.")
        return
    
    keyword = keyword_match.group(0)
    logger.info(f"Extracted keyword: {keyword} using pattern: {matched_pattern}")
    
    # Clean up the keyword - remove any spaces, dashes, or underscores
    cleaned_keyword = keyword.replace(' ', '').replace('-', '').replace('_', '')
    logger.info(f"Cleaned keyword for database lookup: {cleaned_keyword}")
    
    # Get quest by keyword - direct database query for debugging
    try:
        # First, let's log all the keywords in the database for debugging
        if supabase_client:
            all_quests = supabase_client.table("quests").select("keyword,title,active").execute()
            logger.info(f"All quest keywords in database: {[(q['keyword'], q['title'][:20], q['active']) for q in all_quests.data]}")
        
        # Direct database query as a fallback method
        if supabase_client:
            direct_query = supabase_client.table("quests").select("*").eq("keyword", cleaned_keyword).execute()
            if direct_query.data:
                logger.info(f"Direct database query found quest: {direct_query.data[0]['title']}")
            else:
                logger.info(f"Direct database query found NO quest for keyword: {cleaned_keyword}")
        
        # Original fetch_quest call
        quest = fetch_quest(keyword=cleaned_keyword)
        if not quest:
            logger.info(f"No quest found for keyword: {cleaned_keyword}")
            await message.reply_text(f"⚠️ No matching quest found for the keyword '{cleaned_keyword}'. Available keywords are shown in quest details.")
            return
        
        logger.info(f"Found quest for keyword {cleaned_keyword}: {quest['title']} (ID: {quest['id']})")
        
        # Get user, create if doesn't exist
        user = fetch_user(message.from_user.id)
        if not user:
            # Create user if they don't exist
            logger.info(f"Creating new user for ID: {message.from_user.id}")
            user = create_user(
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            logger.info(f"Created new user: {user['id']}")
        else:
            logger.info(f"Found existing user: {user['id']}, username: {user['username']}")
        
        # Check if user already has a submission for this quest
        existing_submissions = fetch_submissions_by_user(user_id=user['id'], quest_id=quest['id'])
        logger.info(f"Found {len(existing_submissions)} existing submissions for this user and quest")
        
        if existing_submissions and len(existing_submissions) > 0:
            # User already has a submission
            if any(sub['status'] == 'approved' for sub in existing_submissions):
                await message.reply_text("⚠️ You already have an approved submission for this quest.")
                return
            
            # Has pending submission
            if any(sub['status'] == 'pending' for sub in existing_submissions):
                await message.reply_text("⚠️ You already have a pending submission for this quest. Please wait for it to be reviewed.")
                return
        
        # Create submission
        logger.info(f"Creating new submission for user {user['id']} and quest {quest['id']}")
        submission = create_submission(
            user_id=user['id'],
            quest_id=quest['id'],
            message_id=message.message_id,
            photo_file_id=photo_file_id,
            video_file_id=video_file_id,
            caption=caption
        )
        
        if submission:
            # Success
            logger.info(f"Created submission: {submission['id']}")
            
            # Forward to admin
            logger.info(f"Attempting to forward submission {submission['id']} to admin group")
            forward_success = await forward_submission_to_admin(context, submission, quest, user)
            
            if forward_success:
                logger.info(f"Successfully forwarded submission {submission['id']} to admin group")
                await message.reply_text(f"✅ Your submission for quest '{quest['title']}' has been received and is pending review. Admin has been notified.")
            else:
                logger.error(f"Failed to forward submission {submission['id']} to admin group")
                await message.reply_text(f"✅ Your submission for quest '{quest['title']}' has been received and is pending review. However, there was an issue notifying admins. They will review your submission as soon as possible.")
        else:
            # Error
            logger.error("Failed to create submission in database")
            await message.reply_text("⚠️ Failed to create submission. Please try again later.")
    
    except Exception as e:
        logger.exception(f"Error handling submission: {e}")
        await message.reply_text("⚠️ An error occurred while processing your submission. Please try again later.")
        return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline buttons."""
    query = update.callback_query
    await query.answer()
    
    # Handle quest pagination
    if query.data.startswith("questpage_"):
        await handle_quest_pagination(update, context)
        return
    
    # Handle party pagination in quest creation
    if query.data.startswith("partypage_"):
        page = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_party":
            # Update the party page
            user_sessions[user_id]["pagination"]["party_page"] = page
            
            # Show party options for the current page
            await display_party_selection(query, user_id, page)
        return
    
    # Handle category pagination in quest creation
    if query.data.startswith("categorypage_"):
        page = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_category":
            # Update the category page
            user_sessions[user_id]["pagination"]["category_page"] = page
            party_name = user_sessions[user_id]["quest_data"]["party_name"]
            
            # Show category options for the current page
            await display_category_selection(query, user_id, party_name, page)
        return
    
    # Processing quest creation steps
    if query.data.startswith("party_"):
        party_name = query.data.replace("party_", "")
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_party":
            if party_name == "skip":
                # Skip party selection but set a default value
                user_sessions[user_id]["quest_data"]["party_name"] = "General"
                # Also set a default category type since we're skipping that step
                user_sessions[user_id]["quest_data"]["category_type"] = "General"
                user_sessions[user_id]["state"] = "awaiting_validation"
                
                # Show validation type options
                keyboard = [
                    [InlineKeyboardButton("Photo", callback_data="validation_photo")],
                    [InlineKeyboardButton("Video", callback_data="validation_video")],
                    [InlineKeyboardButton("Text", callback_data="validation_text")]
                ]
                
                await query.edit_message_text(
                    text="Party and category selection skipped (using 'General' for both). Now choose a validation type:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                user_sessions[user_id]["quest_data"]["party_name"] = party_name
                user_sessions[user_id]["state"] = "awaiting_category"
                user_sessions[user_id]["pagination"]["category_page"] = 1
                
                # Display category selection with pagination
                await display_category_selection(query, user_id, party_name, 1)
    
    elif query.data.startswith("category_"):
        category_type = query.data.replace("category_", "")
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_category":
            if category_type == "skip":
                # Skip category selection but set a default value
                user_sessions[user_id]["quest_data"]["category_type"] = "General"
                user_sessions[user_id]["state"] = "awaiting_validation"
            else:
                user_sessions[user_id]["quest_data"]["category_type"] = category_type
                user_sessions[user_id]["state"] = "awaiting_validation"
            
            # Show validation type options
            keyboard = [
                [InlineKeyboardButton("Photo", callback_data="validation_photo")],
                [InlineKeyboardButton("Video", callback_data="validation_video")],
                [InlineKeyboardButton("Text", callback_data="validation_text")]
            ]
            
            message_text = "Now choose a validation type:"
            if category_type == "skip":
                message_text = "Category selection skipped (using 'General'). Now choose a validation type:"
            
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    elif query.data.startswith("validation_"):
        validation_type = query.data.replace("validation_", "")
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_validation":
            user_sessions[user_id]["quest_data"]["validation_type"] = validation_type.capitalize()
            user_sessions[user_id]["state"] = "awaiting_deadline"
            
            await query.edit_message_text(
                text=f"Selected validation type: {validation_type.capitalize()}\nNow provide a deadline (YYYY-MM-DD or 'everyday'):"
            )
    
    # Processing points selection
    elif query.data.startswith("points_"):
        points = int(query.data.replace("points_", ""))
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_points":
            user_sessions[user_id]["quest_data"]["points"] = points
            
            # Ask user if they want to upload or generate an image
            user_sessions[user_id]["state"] = "awaiting_image_choice"
            
            # Create keyboard with image options
            keyboard = [
                [
                    InlineKeyboardButton("🖼️ Upload Image", callback_data="image_upload"),
                    InlineKeyboardButton("🎨 Generate", callback_data="image_generate")
                ]
            ]
            
            await query.edit_message_text(
                text=f"Selected points: {points}\n\nHow would you like to add an image to this quest?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    # Processing image option selection
    elif query.data.startswith("image_"):
        image_option = query.data.replace("image_", "")
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_image_choice":
            if image_option == "upload":
                # Prompt user to upload an image
                user_sessions[user_id]["state"] = "awaiting_image_upload"
                await query.edit_message_text(
                    "Please send a photo to use as the quest badge. The image should be clear and relevant to the quest."
                )
                return
            elif image_option == "generate":
                # Show icon category selection
                user_sessions[user_id]["state"] = "awaiting_icon_selection"
                
                # Create keyboard with icon categories from icon_provider
                keyboard = []
                categories = icon_provider.get_all_categories() # Now uses the PNG-based categories
                
                # Simple list for now, consider pagination if list gets very long
                for cat in categories:
                     # Use the nicely formatted name for the button, and the key/id for callback
                     keyboard.append([InlineKeyboardButton(
                         cat['name'], 
                         callback_data=f"icon_{cat['id']}" # Use the category ID (filename key)
                     )])
                
                if not categories:
                     logger.error("No icon categories found from icon_provider.get_all_categories()")
                     await query.edit_message_text(
                         text="Error: Could not load icon categories. Proceeding without icon selection."
                     )
                     # Skip icon step - directly to confirmation
                     user_sessions[user_id]["state"] = "awaiting_confirmation"
                     await show_confirmation_preview(context, query, user_id, user_sessions[user_id]["quest_data"])
                     return
                     
                await query.edit_message_text(
                    text="Choose a culture for your quest",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
    
    # Processing icon category selection            
    elif query.data.startswith("icon_"):
        category_id = query.data.replace("icon_", "") # This is now the filename key, e.g., "zo spiritual"
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_icon_selection":
            try:
                # Get icon for the selected category (filename key)
                logger.info(f"Selected icon category ID: {category_id}")
                
                # Generate the icon (now loads the PNG)
                icon = icon_provider.get_icon_by_category(category_id)
                
                if icon is None:
                    logger.error(f"Failed to load icon for category ID: {category_id}")
                    await query.answer(f"Error loading icon for {category_id}. Using default.", show_alert=True)
                    icon = icon_provider.get_icon_by_category("default") # Attempt to load default
                    if icon is None:
                         logger.error("FATAL: Failed to load even the default icon!")
                         await query.edit_message_text("Critical error: Could not load default icon. Aborting quest creation.")
                         del user_sessions[user_id]
                         return # Abort
                
                # Store the icon category ID in user session
                user_sessions[user_id]["icon_category"] = category_id
                
                # Get quest data for badge generation
                quest_data = user_sessions[user_id]["quest_data"]
                
                # Create a temporary quest ID for badge generation
                temp_quest_id = f"preview_{int(time.time())}"
                
                # Generate the complete badge with the loaded PNG icon
                action = quest_data["validation_type"]
                badge_result_buffer = badge_generator.generate_quest_badge(
                    quest_data["title"], 
                    quest_data["description"],
                    action,
                    quest_data["deadline"],
                    temp_quest_id,
                    quest_data["points"],
                    icon  # Pass the loaded PIL.Image object
                )
                
                if badge_result_buffer is None:
                     logger.error("badge_generator.generate_quest_badge returned None")
                     await query.edit_message_text("Error generating the badge preview.")
                     # Keep state to allow trying again?
                     return
                     
                # Move to confirmation state
                user_sessions[user_id]["state"] = "awaiting_confirmation"
                
                # Create quest preview
                preview = (
                    f"📋 QUEST PREVIEW 📋\n\n"
                    f"Title: {quest_data['title']}\n"
                    f"Description: {quest_data['description']}\n"
                )
                
                # Add optional fields if they exist
                if quest_data.get("category_type"):
                    preview += f"Category: {quest_data['category_type']}\n"
                if quest_data.get("party_name"):
                    preview += f"Party: {quest_data['party_name']}\n"
                
                # Get the formatted name for display
                category_info = next((c for c in icon_provider.get_all_categories() if c['id'] == category_id), None)
                category_display = category_info['name'] if category_info else category_id # Fallback to ID
                
                preview += (
                    f"Validation Type: {quest_data['validation_type']}\n"
                    f"Points: {quest_data['points']}\n"
                    f"Deadline: {quest_data['deadline']}\n\n"
                    f"Icon: {category_display}"
                )
                
                # Add confirmation buttons
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Create Quest", callback_data="confirm_quest"),
                        InlineKeyboardButton("❌ Cancel", callback_data="reject_quest")
                    ]
                ]
                
                # Send preview with the generated badge
                # badge_bytes = badge_result if badge_result else icon_provider.get_icon_to_bytes(icon)
                # badge_bytes.seek(0)
                badge_result_buffer.seek(0)
                
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=badge_result_buffer,
                    caption=preview,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Edit the original message to prevent confusion
                await query.edit_message_text(
                    text=f"✅ Badge generated with {category_display} icon. Check the preview below."
                )
                
            except Exception as e:
                logger.error(f"Error processing icon selection or generating badge: {e}")
                await query.answer(f"Error processing icon: {e}")
                # Keep the state as awaiting_icon_selection
    
    # Process quest confirmation
    elif query.data == "confirm_quest":
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_confirmation":
            try:
                # Get quest data from user session
                quest_data = user_sessions[user_id]["quest_data"]
                
                # Create a keyword for the quest using the utility function
                keyword = quest_utils.create_quest_keyword(quest_data["title"])
                
                # Create quest data with only columns that exist in the schema
                quest = {}
                
                # Add required fields - making sure to use the exact column names from the database
                quest["title"] = quest_data["title"]
                quest["description"] = quest_data["description"]
                quest["validation_type"] = quest_data["validation_type"]
                quest["points"] = quest_data["points"]
                quest["deadline"] = quest_data["deadline"]
                quest["keyword"] = keyword
                
                # Handle both keyword versions since schema shows both 'keyword' and 'Keyword'
                quest["Keyword"] = keyword
                
                # Add party_name (required by database constraint)
                quest["party_name"] = quest_data.get("party_name", "Default")
                
                # Explicitly set category_type in the exact format the database expects
                quest["category_type"] = quest_data.get("category_type", "General")
                
                # Add created_by (required by database constraint)
                quest["created_by"] = user_id
                
                # Debug logging to help troubleshoot
                logging.info(f"Final quest data with category: {quest}")
                logging.info(f"Available columns: {available_columns}")
                
                # Add optional fields only if they exist in the schema
                if 'active' in available_columns:
                    quest["active"] = True
                
                # Insert the quest to get an ID
                try:
                    logging.info(f"Attempting to insert quest with data: {quest}")
                    # Remove await here, execute() is synchronous
                    result = supabase_client.table('quests').insert(quest).execute()
                    
                    if not result.data:
                        logging.error("Insertion resulted in no data returned")
                        raise Exception("Failed to create quest")
                    
                    quest_id = result.data[0]['id']
                    logging.info(f"New quest created with ID {quest_id}")
                    
                    # Generate badge if we have an icon category
                    if user_sessions[user_id].get("icon_category"):
                        try:
                            # Get the selected icon
                            icon_category = user_sessions[user_id]["icon_category"]
                            logging.info(f"Generating badge with {icon_category} icon for quest: {quest_id}")
                            
                            # Get the icon image
                            icon = icon_provider.get_icon_by_category(icon_category)
                            
                            # Generate badge using badge_generator.py with the icon
                            action = quest_data["validation_type"]
                            badge_result = badge_generator.generate_quest_badge(
                                quest_data["title"], 
                                quest_data["description"],
                                action,
                                quest_data["deadline"],
                                quest_id,
                                quest_data["points"],
                                icon  # Pass the icon to the badge generator
                            )
                            
                            if badge_result:
                                logging.info(f"Badge generated and stored in Supabase for quest {quest_id}")
                            else:
                                logging.error("Badge generation failed")
                        except Exception as e:
                            logging.error(f"Error generating badge: {e}")
                    
                    # Send success message
                    status_message = f"✅ Quest created successfully!\n\nID: {quest_id}\nTitle: {quest_data['title']}"
                    
                    if user_sessions[user_id].get("icon_category"):
                        category_info = next((c for c in icon_provider.get_all_categories() 
                                             if c['id'] == user_sessions[user_id]["icon_category"]), None)
                        category_display = f"{category_info['symbol']} {category_info['name']}" if category_info else user_sessions[user_id]["icon_category"]
                        status_message += f"\nIcon: {category_display}"
                    
                    # Edit the message caption (since it was likely a photo preview)
                    try:
                        await query.edit_message_caption(caption=status_message)
                    except telegram.error.BadRequest as e:
                        # Fallback if it wasn't a photo message (e.g., image upload failed)
                        if "message is not modified" in str(e).lower():
                            # Ignore if message content is the same
                            pass
                        elif "message to edit not found" in str(e).lower():
                             logger.warning("Original message for edit not found.")
                        else:
                            # Try editing text as a last resort
                            try:
                                await query.edit_message_text(text=status_message)
                            except Exception as text_edit_e:
                                logger.error(f"Failed to edit message text as fallback: {text_edit_e}")
                    
                    # Change user session state to awaiting announcement
                    user_sessions[user_id]["state"] = "awaiting_announcement"
                    user_sessions[user_id]["quest_id"] = quest_id
                    
                    # Create inline keyboard for announcement
                    keyboard = [
                        [
                            InlineKeyboardButton("📣 Announce", callback_data=f"announce_{quest_id}"),
                            InlineKeyboardButton("🔕 Don't announce", callback_data="no_announce")
                        ]
                    ]
                    
                    await query.message.reply_text(
                        f"Do you want to announce this quest to all groups?",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                except Exception as db_error:
                    logging.error(f"Database error details: {db_error}")
                    if "duplicate key" in str(db_error).lower() or "unique constraint" in str(db_error).lower():
                        await query.answer("A quest with this title already exists. Please try a different title.")
                    else:
                        # Log the full error to better understand the issue
                        logging.error(f"Detailed DB error: {type(db_error)}, {str(db_error)}")
                        raise db_error
            except Exception as e:
                logging.error(f"Error confirming quest: {e}")
                await query.answer("Error confirming quest. Please try again.")
                
                # Reset user session
                del user_sessions[user_id]
        else:
            await query.answer("You don't have an active quest creation session.")
    
    elif query.data == "reject_quest":
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_confirmation":
            try:
                # Just show a simple message and reset the session
                await query.edit_message_text(
                    text="Quest creation cancelled. Use /newquest to start again."
                )
                
                # Clear session
                del user_sessions[user_id]
                
            except Exception as e:
                logging.error(f"Error rejecting quest: {e}")
                await query.answer(f"Error: {str(e)}")
                # Still try to clean up the session
                if user_id in user_sessions:
                    del user_sessions[user_id]
    
    # Handling announcement choice
    elif query.data.startswith("announce_"):
        user_id = query.from_user.id
        quest_id = query.data.replace("announce_", "")
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_announcement":
            try:
                # Get quest data from database
                quest = supabase_client.table("quests").select("*").eq("id", quest_id).execute()
                
                if not quest.data:
                    raise Exception("Quest not found")
                
                quest_data = quest.data[0]
                
                # Create announcement message with new format
                announcement = (
                    f"Zo Zo Trippers New Quest up for grabs.\n\n"
                    f"Title: {quest_data['title']}\n"
                    f"Description: {quest_data['description']}\n"
                    f"Points: {quest_data['points']}\n"
                    f"Deadline: {quest_data['deadline']}\n\n"
                    f"To complete this quest, post a {quest_data['validation_type'].lower()} with the exact keyword '{quest_data['keyword']}' in your caption."
                )
                
                # Try to get badge image data from the badge_images table
                try:
                    badge_image = supabase_client.table("badge_images").select("image_data").eq("quest_id", str(quest_id)).execute()
                    
                    if badge_image.data and badge_image.data[0].get("image_data"):
                        # Decode base64 image data and convert to bytes
                        img_data = base64.b64decode(badge_image.data[0]["image_data"])
                        img_buffer = io.BytesIO(img_data)
                        img_buffer.seek(0)
                        
                        # Send the badge image
                        await context.bot.send_photo(
                            chat_id=PUBLIC_GROUP_ID,
                            photo=img_buffer,
                            caption=announcement
                        )
                        logger.info(f"Announced quest {quest_id} with badge from database")
                        return
                except Exception as db_error:
                    logger.error(f"Error retrieving badge from database: {db_error}")
                
                # If no badge found in Supabase, fall back to Telegram file ID if available
                if user_sessions[user_id].get("image_file_id"):
                    await context.bot.send_photo(
                        chat_id=PUBLIC_GROUP_ID, 
                        photo=user_sessions[user_id]["image_file_id"],
                        caption=announcement
                    )
                else:
                    # If no image at all, just send a text announcement
                    await context.bot.send_message(chat_id=PUBLIC_GROUP_ID, text=announcement)
                
                # Update confirmation message
                if hasattr(query.message, 'caption'):
                    await query.edit_message_caption(
                        caption=f"✅ Quest created and announced successfully!"
                    )
                else:
                    await query.edit_message_text(
                        text=f"✅ Quest created and announced successfully!"
                    )
                
                # Clear session
                del user_sessions[user_id]
                
            except Exception as e:
                logger.error(f"Error announcing quest: {e}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"An error occurred while announcing the quest: {e}"
                )
                # Clear the session
                del user_sessions[user_id]
    
    elif query.data == "no_announce":
        user_id = query.from_user.id
        
        if user_id in user_sessions and user_sessions[user_id]["state"] == "awaiting_announcement":
            if hasattr(query.message, 'caption'):
                await query.edit_message_caption(
                    caption="✅ Quest created successfully (not announced)."
                )
            else:
                await query.edit_message_text(
                    text="✅ Quest created successfully (not announced)."
                )
            # Clear session
            del user_sessions[user_id]
    
    # Processing submission approval/rejection
    elif query.data.startswith("approve_") or query.data.startswith("reject_"):
        is_approval = query.data.startswith("approve_")
        submission_id = query.data.split("_")[1]
        admin_id = query.from_user.id
        admin_name = query.from_user.name
        chat_id = update.effective_chat.id
        
        # Ensure this is happening in the admin group using normalized comparison
        logger.info(f"Checking if {chat_id} is admin group {ADMIN_GROUP_ID}")
        if str(chat_id) != ADMIN_GROUP_ID and normalize_group_id(chat_id) != normalize_group_id(ADMIN_GROUP_ID):
            logger.warning(f"Approval/rejection attempted in wrong chat: {chat_id}, expected {ADMIN_GROUP_ID}")
            await query.answer("This action can only be performed in the admin group.")
            return
        
        try:
            # Update submission status
            status = "approved" if is_approval else "rejected"
            supabase_client.table("submissions").update({
                "status": status,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now().isoformat()
            }).eq("id", submission_id).execute()
            
            # Get submission and quest details
            submission = supabase_client.table("submissions").select("*").eq("id", submission_id).execute().data[0]
            quest = supabase_client.table("quests").select("*").eq("id", submission["quest_id"]).execute().data[0]
            user = supabase_client.table("users").select("*").eq("id", submission["user_id"]).execute().data[0]
            
            # If approved, update user points
            if is_approval:
                # Update user points
                new_points = user["total_points"] + quest["points"]
                
                supabase_client.table("users").update({
                    "total_points": new_points
                }).eq("id", submission["user_id"]).execute()
                
                # Removed public notification in PUBLIC_GROUP_ID as requested
                
                # Send a direct message to the user if possible
                try:
                    user_notification = (
                        f"🎉 Good news! Your submission for '{quest['title']}' has been approved.\n\n"
                        f"• Points earned: {quest['points']}\n"
                        f"• Approved by: {admin_name}\n"
                        f"• New total: {new_points} points\n\n"
                        f"Keep up the great work! 🚀"
                    )
                    await context.bot.send_message(
                        chat_id=user["id"],
                        text=user_notification
                    )
                except Exception as e:
                    logger.error(f"Error sending direct message to user {user['id']}: {e}")
            else:
                # Only notify user via direct message about rejection - no public notification
                
                # Send a direct message to the user if possible
                try:
                    user_notification = (
                        f"Your submission for '{quest['title']}' was not approved.\n\n"
                        f"• Reviewed by: {admin_name}\n\n"
                        f"You can try again by sending another submission with the keyword '{quest['keyword']}' in the caption."
                    )
                    await context.bot.send_message(
                        chat_id=user["id"],
                        text=user_notification
                    )
                except Exception as e:
                    logger.error(f"Error sending direct message to user {user['id']}: {e}")
            
            # Update admin message
            action = "Approved" if is_approval else "Rejected"
            await query.edit_message_caption(
                caption=f"{action}: {query.message.caption}",
                reply_markup=None
            )
            
            # Send confirmation message to admin group
            confirmation_message = (
                f"✅ Submission {action.lower()} by {admin_name} (ID: {admin_id})!\n\n"
                f"Quest: {quest['title']}\n"
                f"User: {user['username'] or user['first_name']} (ID: {user['id']})\n"
                f"Points: {quest['points']}\n"
                f"Status: {status.capitalize()}\n"
                f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=confirmation_message
            )
            
        except Exception as e:
            logger.error(f"Error processing submission {submission_id}: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Error processing submission: {e}"
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for multi-step commands."""
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    logger.info(f"Received text message: '{message_text}' from user {user_id}")
    
    try:
        # Check if we're in a session for quest creation process
        if user_id in user_sessions:
            session = user_sessions[user_id]
            logger.info(f"User {user_id} has active session state: {session['state']}")
            
            if session["state"] == "awaiting_title":
                logger.info(f"Processing awaiting_title state for user {user_id}")
                session["quest_data"]["title"] = update.message.text
                session["state"] = "awaiting_description"
                await update.message.reply_text("Great! Now provide a description for the quest:")
                logger.info(f"Updated state for user {user_id} to awaiting_description")
            
            elif session["state"] == "awaiting_description":
                logger.info(f"Processing awaiting_description state for user {user_id}")
                session["quest_data"]["description"] = update.message.text
                session["state"] = "awaiting_party"
                
                # Initialize pagination
                session["pagination"]["party_page"] = 1
                
                # Show paginated party options
                keyboard = []
                
                # Get first page of parties
                parties_to_show = PARTY_NAMES[:ITEMS_PER_PAGE]
                for party in parties_to_show:
                    keyboard.append([InlineKeyboardButton(party, callback_data=f"party_{party}")])
                
                # Add navigation if needed
                if len(PARTY_NAMES) > ITEMS_PER_PAGE:
                    keyboard.append([InlineKeyboardButton("▶️", callback_data="partypage_2")])
                    
                # Add Skip button
                keyboard.append([InlineKeyboardButton("Skip", callback_data="party_skip")])
                
                await update.message.reply_text(
                    f"Now select the party name:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logger.info(f"Updated state for user {user_id} to awaiting_party and sent options")
            
            elif session["state"] == "awaiting_deadline":
                logger.info(f"Processing awaiting_deadline state for user {user_id}")
                session["quest_data"]["deadline"] = update.message.text
                session["state"] = "awaiting_points"
                
                # Show points options
                keyboard = []
                row = []
                for i, points in enumerate(POINT_VALUES, 1):
                    row.append(InlineKeyboardButton(str(points), callback_data=f"points_{points}"))
                    if i % 3 == 0:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                
                await update.message.reply_text(
                    "Select points value for this quest:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logger.info(f"Updated state for user {user_id} to awaiting_points and sent options")
                
            elif session["state"] == "awaiting_image":
                # No special text handling needed for image state
                # Users should upload a photo or use the buttons
                logger.info(f"User {user_id} is in awaiting_image state but sent text")
                await update.message.reply_text(
                    "Please either upload an image or use the Generate button from the previous message."
                )
            else:
                logger.info(f"User {user_id} is in an unhandled state: {session['state']}")
                await update.message.reply_text(
                    f"I'm waiting for something else right now. Your current state is: {session['state']}"
                )
        else:
            logger.info(f"User {user_id} sent text but is not in any active session")
            # Text is not for quest creation, let other handlers process it
    except Exception as e:
        logger.error(f"Error in handle_text for user {user_id}, state {user_sessions.get(user_id, {}).get('state', 'None')}: {e}")
        logger.error(f"Full exception details: {repr(e)}")
        try:
            await update.message.reply_text("Sorry, something went wrong processing your input. Please try again or use /cancel to restart.")
        except Exception as reply_error:
            logger.error(f"Error sending error message: {reply_error}")
    # DO NOT try to handle quest detail requests here
    # They are already handled by the quests_conv_handler ConversationHandler

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads during quest creation."""
    logger.info("handle_photo called")
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if this is in the admin group for quest creation using normalized comparison
    logger.info(f"Checking if {chat_id} is admin group {ADMIN_GROUP_ID}")
    if str(chat_id) != ADMIN_GROUP_ID and normalize_group_id(chat_id) != normalize_group_id(ADMIN_GROUP_ID):
        logger.warning(f"Quest photo upload attempted in wrong chat: {chat_id}, expected {ADMIN_GROUP_ID}")
        return
    
    if user_id in user_sessions:
        logger.info(f"User {user_id} is in quest creation mode")
        # User is in quest creation process
        session = user_sessions[user_id]
        
        # Get the photo file_id 
        photo_file_id = update.message.photo[-1].file_id
        
        # Update session with photo details
        session["photo_id"] = photo_file_id
        user_sessions[user_id] = session
        
        # Generate preview of quest
        preview = f"📝 *QUEST PREVIEW*\n\n"
        preview += f"*Title:* {session.get('title', '(not set)')}\n"
        preview += f"*Description:* {session.get('description', '(not set)')}\n"
        preview += f"*Category:* {session.get('category', '(not set)')}\n"
        preview += f"*Party Name:* {session.get('party_name', '(not set)')}\n"
        preview += f"*Total Budget:* {session.get('budget', 0)} ZO\n"
        preview += f"*Reward:* {session.get('reward', 0)} ZO\n"
        preview += f"*Number of Quests:* {session.get('num_quests', 0)}\n"
        
        # Create confirmation keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Create Quest", callback_data="confirm_quest"),
                InlineKeyboardButton("❌ Cancel", callback_data="reject_quest")
            ]
        ]
        
        try:
            # Send preview with the image
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_file_id,
                caption=preview,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending preview: {e}")
            # Fall back to text-only if sending photo fails
            await update.message.reply_text(
                text=f"{preview}\n\n(Image preview not available)",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    # We don't need an else clause as we now have separate handlers

async def display_party_selection(query, user_id, page):
    """Display paginated party selection options."""
    # Calculate total pages
    total_items = len(PARTY_NAMES)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # Ceiling division
    
    # Ensure page is in valid range
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    # Calculate start and end indices
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    
    # Get parties for current page
    page_parties = PARTY_NAMES[start_idx:end_idx]
    
    # Create keyboard
    keyboard = []
    for party in page_parties:
        keyboard.append([InlineKeyboardButton(party, callback_data=f"party_{party}")])
    
    # Add pagination navigation
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"partypage_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"partypage_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Add Skip button always at the bottom
    keyboard.append([InlineKeyboardButton("Skip", callback_data="party_skip")])
    
    # Edit message with new keyboard
    await query.edit_message_text(
        text=f"Select party name:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def display_category_selection(query, user_id, party_name, page):
    """Display paginated category selection options."""
    categories = CATEGORY_TYPES.get(party_name, [])
    
    # Calculate total pages
    total_items = len(categories)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # Ceiling division
    
    # Ensure page is in valid range
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    
    # Calculate start and end indices
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    
    # Get categories for current page
    page_categories = categories[start_idx:end_idx]
    
    # Create keyboard
    keyboard = []
    for category in page_categories:
        keyboard.append([InlineKeyboardButton(category, callback_data=f"category_{category}")])
    
    # Add pagination navigation
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"categorypage_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"categorypage_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Add Skip button always at the bottom
    keyboard.append([InlineKeyboardButton("Skip", callback_data="category_skip")])
    
    # Edit message with new keyboard
    await query.edit_message_text(
        text=f"Selected party: {party_name}\nNow choose a category type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Error handler (keep as is)
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    error_msg = f"Update {update} caused error {context.error}"
    logger.error(error_msg)
    
    # Log more detailed error information
    logger.error(f"Error type: {type(context.error)}")
    logger.error(f"Error details: {str(context.error)}")
    
    if update:
        if update.message:
            logger.error(f"Message text: {update.message.text}")
            logger.error(f"From user: {update.message.from_user.id} - {update.message.from_user.username}")
        elif update.callback_query:
            logger.error(f"Callback data: {update.callback_query.data}")

# Special debug handler to log all incoming updates
async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all updates for debugging."""
    logger.info(f"DEBUG: Received update type: {update.effective_message.text if update.effective_message else update}")
    # Let other handlers process this update
    return None

def main():
    """Start the bot."""
    logger.info("Starting main function...")
    
    # Initialize the Application
    application = None
    try:
        logger.info("Initializing Telegram Application...")
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("Telegram Application initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Telegram Application: {e}")
        sys.exit(1)

    # --- Add Handlers --- 
    # Remove debug handler that logs all updates
    
    # Define InSessionFilter here, before it's used
    class InSessionFilter(filters.MessageFilter):
        def filter(self, message):
            return message.from_user.id in user_sessions
    in_session_filter = InSessionFilter()
    
    # Register direct command handlers
    # (These commands don't need conversation states)
    # Each command is registered exactly ONCE to prevent double responses
    application.add_handler(CommandHandler("newquest", new_quest), group=-2)
    logger.info("Registered /newquest command handler")
    application.add_handler(CommandHandler("leaderboard", leaderboard), group=-2)
    logger.info("Registered /leaderboard command handler")
    application.add_handler(CommandHandler("tripper", tripper_info), group=-2)
    logger.info("Registered /tripper command handler")
    application.add_handler(CommandHandler("cancel", cancel), group=-2)
    logger.info("Registered /cancel command handler")

    # Text handler specifically for quest creation with higher priority
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & in_session_filter, handle_text), group=-1)
    logger.info("Registered quest creation text handler with high priority")

    # Conversation handler for /start (handles wallet collection for new users)
    start_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start)
        ],
        states={
            WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_wallet)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="wallet_conversation",
        persistent=False
    )
    application.add_handler(start_conv_handler, group=1)
    logger.info("Registered /start conversation handler")

    # Separate conversation handler for /updatewallet
    updatewallet_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("updatewallet", update_wallet_command)
        ],
        states={
            WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_wallet)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="updatewallet_conversation",
        persistent=False
    )
    application.add_handler(updatewallet_conv_handler, group=1)
    logger.info("Registered /updatewallet conversation handler")

    quests_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("viewquests", view_quests)
        ],
        states={
            QUEST_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_quest_detail)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="quests_conversation",
        persistent=False,
        per_chat=False,
        per_user=True,
        per_message=False
    )
    application.add_handler(quests_conv_handler, group=1)
    logger.info("Registered quests conversation handler")

    application.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Registered callback query handler")
    
    # First register the photo handler for quest creation (higher priority)
    application.add_handler(MessageHandler(filters.PHOTO & in_session_filter, handle_photo), group=1)
    logger.info("Registered quest photo handler for users in sessions (priority 1)")
    
    # Then register the submission handler (lower priority)
    # Using a more permissive handler to catch all media with captions
    application.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, handle_submission), group=2)
    logger.info("Registered photo/video submission handler (priority 2)")

    application.add_error_handler(error_handler)
    logger.info("Registered error handler")
    # --- End Handlers --- 

    # Log environment configuration
    logger.info(f"Bot configuration: TOKEN={BOT_TOKEN[:5]}..., ADMIN_GROUP_ID={ADMIN_GROUP_ID}, PUBLIC_GROUP_ID={PUBLIC_GROUP_ID}")
    logger.info(f"Running in {'Webhook' if USE_WEBHOOK else 'Polling'} mode")
    
    # --- Run the Bot --- 
    try:
        logger.info(f"Starting bot in {'Webhook' if USE_WEBHOOK else 'Polling'} mode.")
        
        if USE_WEBHOOK:
            logger.info("Webhook mode activated")
            
            # Use webhook URL from environment
            webhook_url = WEBHOOK_URL
            logger.info(f"Setting webhook to {webhook_url}")
            
            # Let application.run_webhook handle the event loop
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                webhook_url=webhook_url,
                drop_pending_updates=True
            )
        else:
            logger.info("Polling mode activated")
            application.run_polling(drop_pending_updates=True)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
    logger.info("Bot script finished execution.")