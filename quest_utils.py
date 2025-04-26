import logging
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Import db_utils for database operations
import db_utils

# Setup logger
logger = logging.getLogger(__name__)

# Constants for pagination
QUESTS_PER_PAGE = 3
ITEMS_PER_PAGE = 4  # For parties, categories, etc.

# Party and category data - later this could be moved to database
PARTY_NAMES = ["Zo Trip", "FIFA", "Poker", "Founders Connect"]
CATEGORY_TYPES = {
    "Zo Trip": ["Zo 🌌✨ Zo 🌠 | The Initiate Path", "Daily Check-in ✅", "Event-Specific 🎭"],
    "FIFA": ["FIFA Champion 🏆", "FIFA Achievements 🎮", "First Timer 🆕"],
    "Poker": ["Poker Pro 🃏", "Poker Achievements 🎲", "First Timer 🆕"],
    "Founders Connect": ["Networking 🤝", "Special Events 🎉", "Activities 🏄‍♂️"]
}

# Quest points presets
POINT_VALUES = [111, 210, 300, 420, 690, 766]

def paginate_quests(page: int, user_id: int) -> Tuple[List[Dict[str, Any]], Dict[int, Any], Dict[str, Any], int]:
    """
    Paginate quests for display
    
    Args:
        page: Current page number (1-based)
        user_id: User ID for tracking displayed quests
        
    Returns:
        Tuple containing:
        - List of quest data for the current page
        - Dictionary mapping display numbers to quest IDs
        - Pagination info (current_page, total_pages, has_prev, has_next)
        - Total number of pages
    """
    # Fetch active quests
    all_quests = db_utils.fetch_active_quests()
    
    # Get current date in ISO format
    today = datetime.now().date().isoformat()
    
    # Separate future and everyday quests
    future_quests = [q for q in all_quests if q.get("deadline") != "everyday" and q.get("deadline", "") >= today]
    everyday_quests = [q for q in all_quests if q.get("deadline") == "everyday"]
    
    # Sort future quests by deadline
    future_quests.sort(key=lambda x: x.get("deadline", "9999-99-99"))
    
    # Combine lists with future quests first, then everyday quests
    sorted_quests = future_quests + everyday_quests
    
    # Calculate total pages
    total_quests = len(sorted_quests)
    total_pages = (total_quests + QUESTS_PER_PAGE - 1) // QUESTS_PER_PAGE  # Ceiling division
    
    # Ensure page is within valid range
    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages
    
    # Calculate start and end indices for this page
    start_idx = (page - 1) * QUESTS_PER_PAGE
    end_idx = min(start_idx + QUESTS_PER_PAGE, total_quests)
    
    # Get quests for current page
    page_quests = sorted_quests[start_idx:end_idx] if total_quests > 0 else []
    
    # Create mapping from display numbers to quest IDs
    quest_mapping = {}
    for i, quest in enumerate(page_quests, 1):
        quest_mapping[i] = quest["id"]
    
    # Pagination info
    pagination_info = {
        "current_page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages
    }
    
    return page_quests, quest_mapping, pagination_info, total_pages

def format_quest_list(quests: List[Dict[str, Any]]) -> str:
    """
    Format a list of quests for display
    
    Args:
        quests: List of quest dictionaries
        
    Returns:
        Formatted message text
    """
    message = f"📝 AVAILABLE QUESTS 📝\n\n"
    
    if not quests:
        message += "No quests found."
        return message
    
    for i, quest in enumerate(quests, 1):
        # Get deadline
        deadline = quest.get("deadline", "N/A")
        
        # Get points
        points = quest.get("points", "---")
        
        # Show title, points and deadline
        message += f"{i}. {quest.get('title', 'No title')}\n"
        message += f"   {points} pts - {deadline}\n\n"
    
    # Add instruction
    message += "Reply with a number to see quest details\n"
    
    return message

def create_quest_pagination_keyboard(pagination_info: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    """
    Create pagination keyboard for quests list
    
    Args:
        pagination_info: Dictionary with pagination information
        
    Returns:
        InlineKeyboardMarkup or None if no pagination needed
    """
    keyboard = []
    nav_row = []
    
    if pagination_info["has_prev"]:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"questpage_{pagination_info['current_page']-1}"))
    
    if pagination_info["has_next"]:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"questpage_{pagination_info['current_page']+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
        return InlineKeyboardMarkup(keyboard)
    
    return None

def create_paginated_party_keyboard(page: int) -> InlineKeyboardMarkup:
    """
    Create keyboard with paginated party selection options
    
    Args:
        page: Current page number (1-based)
        
    Returns:
        InlineKeyboardMarkup with party buttons and pagination
    """
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
    
    return InlineKeyboardMarkup(keyboard)

def create_paginated_category_keyboard(party_name: str, page: int) -> InlineKeyboardMarkup:
    """
    Create keyboard with paginated category selection options
    
    Args:
        party_name: Selected party name
        page: Current page number (1-based)
        
    Returns:
        InlineKeyboardMarkup with category buttons and pagination
    """
    categories = CATEGORY_TYPES.get(party_name, [])
    
    # Calculate total pages
    total_items = len(categories)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # Ceiling division
    
    # Ensure page is in valid range
    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages
    
    # Calculate start and end indices
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    
    # Get categories for current page
    page_categories = categories[start_idx:end_idx] if total_items > 0 else []
    
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
    
    return InlineKeyboardMarkup(keyboard)

def create_validation_type_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard with validation type options
    
    Returns:
        InlineKeyboardMarkup with validation type buttons
    """
    keyboard = [
        [InlineKeyboardButton("Photo", callback_data="validation_photo")],
        [InlineKeyboardButton("Video", callback_data="validation_video")],
        [InlineKeyboardButton("Text", callback_data="validation_text")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def create_points_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard with points options
    
    Returns:
        InlineKeyboardMarkup with points buttons
    """
    keyboard = []
    row = []
    
    for i, points in enumerate(POINT_VALUES, 1):
        row.append(InlineKeyboardButton(str(points), callback_data=f"points_{points}"))
        if i % 3 == 0:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

def create_image_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard with image choice options
    
    Returns:
        InlineKeyboardMarkup with image choice buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("🖼️ Upload Image", callback_data="image_upload"),
            InlineKeyboardButton("🎨 Generate", callback_data="image_generate")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def create_quest_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for quest confirmation
    
    Returns:
        InlineKeyboardMarkup with confirmation buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Create Quest", callback_data="confirm_quest"),
            InlineKeyboardButton("❌ Cancel", callback_data="reject_quest")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def create_announcement_keyboard(quest_id: str) -> InlineKeyboardMarkup:
    """
    Create keyboard for quest announcement choice
    
    Args:
        quest_id: ID of the created quest
        
    Returns:
        InlineKeyboardMarkup with announcement buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("📣 Announce", callback_data=f"announce_{quest_id}"),
            InlineKeyboardButton("🔕 Don't announce", callback_data="no_announce")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def format_quest_details(quest: Dict[str, Any]) -> str:
    """
    Format quest details for display
    
    Args:
        quest: Quest dictionary
        
    Returns:
        Formatted message text with quest details
    """
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
        f"with the exact keyword '{quest.get('keyword', '')}' in your caption."
    )
    
    return detail_message

def format_quest_preview(quest_data: Dict[str, Any], icon_category: Optional[str] = None) -> str:
    """
    Format quest preview for confirmation
    
    Args:
        quest_data: Dictionary with quest data
        icon_category: Selected icon category, if applicable
        
    Returns:
        Formatted message text with quest preview
    """
    preview = (
        f"📋 QUEST PREVIEW 📋\n\n"
        f"Title: {quest_data.get('title', '(not set)')}\n"
        f"Description: {quest_data.get('description', '(not set)')}\n"
    )
    
    # Add optional fields if they exist
    if quest_data.get("category_type"):
        preview += f"Category: {quest_data.get('category_type')}\n"
    if quest_data.get("party_name"):
        preview += f"Party: {quest_data.get('party_name')}\n"
    
    preview += (
        f"Validation Type: {quest_data.get('validation_type', '(not set)')}\n"
        f"Points: {quest_data.get('points', '(not set)')}\n"
        f"Deadline: {quest_data.get('deadline', '(not set)')}\n"
    )
    
    if icon_category:
        preview += f"\nIcon: {icon_category}"
    
    return preview

def create_quest_keyword(title: str) -> str:
    """
    Create a keyword for a quest based on its title
    
    Args:
        title: Quest title
        
    Returns:
        Keyword string
    """
    # Use a deterministic hash approach for consistent keywords
    base_keyword = title.lower().replace(" ", "_")
    # Use a simple hash function to generate a 3-digit number
    title_hash = 0
    for char in base_keyword:
        title_hash = (title_hash * 31 + ord(char)) % 1000
    # Format with leading zeros to ensure it's always 3 digits
    return f"zozozo{title_hash:03d}" 