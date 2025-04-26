#!/usr/bin/env python3
"""
icon_provider.py - Provides preset icons for quest badges

This module offers a collection of premade icons for quest badges,
organized by categories that can be selected during quest creation.
"""

import os
import io
import logging
import base64
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import PIL

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
# logger.info(f"Using Pillow version: {PIL.__version__}") # No longer needed as we load images

# Constants
ICON_SIZE = 150  # Default icon size (width/height in pixels)
ICON_CACHE = {}  # Cache generated icons in memory

# Define base directory for icons relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(BASE_DIR, "fonts", "Color Symbols")
logger.info(f"Looking for icons in: {ICONS_DIR}")

# Icon categories mapping directly to filenames (without .png)
# Keys MUST exactly match the filenames in fonts/Color Symbols/
ICON_CATEGORIES = {
    # Old Key -> New Key
    "Spiritual": {"description": "Spiritual quests"},                 # zo spiritual
    "Science & tech": {"description": "Science & Technology"},         # zo science & tech
    "Literature": {"description": "Literature & Writing"},             # zo literature
    "Health & Fitness": {"description": "Health & Fitness"},           # zo health & fitness
    "Follow your Heart": {"description": "Follow Your Heart"},         # zo follow your heart
    "Travel & Adventure": {"description": "Travel & Adventure"},       # zo travel & adventure
    "Cinema": {"description": "Television & Cinema"},                # zo television & cinema
    "Storytelling": {"description": "Stories & Journals"},             # zo stories & jornals
    "Sports": {"description": "Sports"},                             # zosports
    "Content": {"description": "Photography & Content Creation"},       # zophotography
    "Podcast": {"description": "Open Mic & Podcasts"},                # zo open mic
    "Nature & Wildlife": {"description": "Nature & Wildlife"},         # zo nature & wildlife
    "Music": {"description": "Music"},                               # zomusic
    "Law & Order": {"description": "Law & Order"},                    # zo law & Order
    "Lifestyle": {"description": "Home & Lifestyle"},               # zo home & lifestyle
    "Games": {"description": "Games"},                               # zogames
    "Food": {"description": "Food"},                                # zofood
    "Design": {"description": "Design"},                             # zodesign
    "Business": {"description": "Business"},                         # zobuisness
    # Using 'Spiritual' as the fallback default
    "default": {"description": "Default/General", "filename": "Spiritual"}
}

# Removed create_text_icon and create_geometric_icon

def get_icon_by_category(category):
    """
    Get an icon by category name by loading its corresponding PNG file.
    Caches the icon if not already cached.

    Args:
        category (str): The icon category (should match a key in ICON_CATEGORIES)

    Returns:
        PIL.Image | None: The icon image or None if loading fails.
    """
    if category not in ICON_CATEGORIES:
        logger.warning(f"Category '{category}' not found, using default.")
        category = "default"

    cache_key = category # Cache based on category name

    # Check cache
    if cache_key in ICON_CACHE:
        return ICON_CACHE[cache_key]

    # Determine filename - use specific filename for default if provided
    config = ICON_CATEGORIES[category]
    filename_base = config.get("filename", category) # Use category name if no specific filename
    filepath = os.path.join(ICONS_DIR, f"{filename_base}.png")

    # Load the icon from PNG file
    try:
        if not os.path.exists(filepath):
            logger.error(f"Icon file not found: {filepath}")
            # Try loading the actual default file as a last resort
            if category != "default": # Avoid infinite loop
                logger.warning("Falling back to actual default icon file.")
                return get_icon_by_category("default")
            else:
                return None # Cannot load even the default

        icon = Image.open(filepath).convert("RGBA")
        logger.info(f"Loaded icon from: {filepath}")

        # Optional: Resize if needed, though ideally they are already 150x150
        # icon = icon.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)

        # Cache the icon
        ICON_CACHE[cache_key] = icon
        return icon

    except Exception as e:
        logger.error(f"Error loading icon file {filepath}: {e}")
        # Fallback to default if loading fails for a specific category
        if category != "default":
             logger.warning("Falling back to default icon due to loading error.")
             return get_icon_by_category("default")
        return None

def get_all_categories():
    """
    Get list of all available icon categories.

    Returns:
        list: List of dictionaries containing category info
    """
    categories = []
    for name, config in ICON_CATEGORIES.items():
        # Exclude the 'default' meta-category from user selection
        if name == "default":
            continue
        categories.append({
            "id": name, # Use the category key as the ID
            # "name": name.replace("zo ", "").replace("&", " & ").replace("z", "Z").capitalize(), # Old formatting
            "name": name, # Use the key directly as it's already formatted nicely
            "description": config["description"],
            "symbol": "🖼️" # Use a generic image symbol now
        })
    # Sort alphabetically by the formatted name
    categories.sort(key=lambda x: x["name"])
    return categories

def get_icon_to_bytes(icon):
    """
    Convert an icon to a bytes object.

    Args:
        icon (PIL.Image): The icon image

    Returns:
        io.BytesIO: BytesIO object containing the PNG image data, or None if icon is None
    """
    if icon is None:
        logger.error("Cannot convert None icon to bytes.")
        return None
    try:
        img_buffer = io.BytesIO()
        icon.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        return img_buffer
    except Exception as e:
        logger.error(f"Error converting icon to bytes: {e}")
        return None

# Removed save_icon_to_file and generate_all_category_icons

# Example usage (optional)
if __name__ == "__main__":
    print("Available Categories:")
    all_cats = get_all_categories()
    for cat in all_cats:
        print(f"  ID: {cat['id']}, Name: {cat['name']}")

    print("\nAttempting to load 'zomusic' icon:")
    music_icon = get_icon_by_category("zomusic")
    if music_icon:
        print(f"Loaded music icon successfully: size {music_icon.size}")
        # music_icon.show() # Uncomment to display locally if needed
    else:
        print("Failed to load music icon.")

    print("\nAttempting to load default icon:")
    default_icon = get_icon_by_category("default")
    if default_icon:
        print(f"Loaded default icon ('{ICON_CATEGORIES['default'].get('filename', 'default')}') successfully: size {default_icon.size}")
    else:
        print("Failed to load default icon.") 