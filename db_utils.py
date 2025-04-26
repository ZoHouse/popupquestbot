import logging
from typing import Any, Optional, Callable, TypeVar, Dict, List, Union

# Setup logger
logger = logging.getLogger(__name__)

# Type variables for generics
T = TypeVar('T')
R = TypeVar('R')

# Global reference to the supabase client that will be set from the main bot
supabase_client = None

def set_supabase_client(client):
    """Set the global supabase client reference"""
    global supabase_client
    supabase_client = client
    logger.info("Supabase client set in db_utils")

def safe_supabase_call(query_function: Callable[[], T], fallback_value: R = None) -> Union[T, R]:
    """
    Execute a Supabase query safely with error handling
    
    Args:
        query_function: A function that when called, executes a Supabase query
        fallback_value: The value to return if the query fails
        
    Returns:
        The result of the query or the fallback value if the query fails
    """
    try:
        result = query_function()
        return result
    except Exception as e:
        logger.error(f"Supabase query error: {e}")
        
        # Log more details if available
        if hasattr(e, 'details'):
            logger.error(f"Error details: {e.details}")
        if hasattr(e, 'message'):
            logger.error(f"Error message: {e.message}")
            
        return fallback_value

def fetch_user(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch a user by their Telegram ID
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        User data dictionary or None if not found/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
        
    result = safe_supabase_call(
        lambda: supabase_client.table("users").select("*").eq("id", user_id).execute(),
        fallback_value={"data": []}
    )
    
    if result and result.data and len(result.data) > 0:
        return result.data[0]
    return None

def create_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Create a new user in the database
    
    Args:
        user_id: Telegram user ID
        username: Optional username
        first_name: Optional first name
        last_name: Optional last name
        
    Returns:
        User dictionary if successful, None otherwise
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
    
    # Prepare user data
    from datetime import datetime
    
    user_data = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "total_points": 0,
        "joined_at": datetime.now().isoformat()
    }
        
    result = safe_supabase_call(
        lambda: supabase_client.table("users").insert(user_data).execute(),
        fallback_value=None
    )
    
    if result and result.data and len(result.data) > 0:
        return result.data[0]
    return None

def update_user(user_id: int, update_data: Dict[str, Any]) -> bool:
    """
    Update user data
    
    Args:
        user_id: Telegram user ID
        update_data: Dictionary with fields to update
        
    Returns:
        True if successful, False otherwise
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return False
        
    result = safe_supabase_call(
        lambda: supabase_client.table("users").update(update_data).eq("id", user_id).execute(),
        fallback_value=None
    )
    
    return result is not None and hasattr(result, 'data')

def fetch_quest(quest_id: Optional[Any] = None, keyword: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch a quest by ID or keyword
    
    Args:
        quest_id: Quest ID (could be int, string, or UUID)
        keyword: Quest keyword string
        
    Returns:
        Quest data dictionary or None if not found/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
    
    if not quest_id and not keyword:
        logger.error("Either quest_id or keyword must be provided")
        return None
    
    # Log the query parameters for debugging
    logger.info(f"Fetching quest with parameters: quest_id={quest_id}, keyword={keyword}")
    
    try:
        if quest_id:
            result = safe_supabase_call(
                lambda: supabase_client.table("quests").select("*").eq("id", quest_id).execute(),
                fallback_value={"data": []}
            )
        else:
            # First try with exact match
            result = safe_supabase_call(
                lambda: supabase_client.table("quests").select("*").eq("keyword", keyword).execute(),
                fallback_value={"data": []}
            )
            
            # Log the result
            logger.info(f"Query result for keyword={keyword}: found {len(result.data)} quests")
            
            # If nothing found and active filter was included, try without it
            if not result.data:
                logger.info(f"No active quests found for keyword={keyword}, trying without active filter")
                result = safe_supabase_call(
                    lambda: supabase_client.table("quests").select("*").eq("keyword", keyword).execute(),
                    fallback_value={"data": []}
                )
        
        if result and result.data and len(result.data) > 0:
            logger.info(f"Found quest: {result.data[0].get('title', 'No title')} with keyword: {result.data[0].get('keyword', 'No keyword')}")
            return result.data[0]
        
        logger.warning(f"No quest found for quest_id={quest_id}, keyword={keyword}")
        return None
        
    except Exception as e:
        logger.exception(f"Error fetching quest: {e}")
        return None

def fetch_active_quests() -> List[Dict[str, Any]]:
    """
    Fetch all active quests
    
    Returns:
        List of quest dictionaries or empty list if none/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return []
        
    result = safe_supabase_call(
        lambda: supabase_client.table("quests").select("*").eq("active", True).execute(),
        fallback_value={"data": []}
    )
    
    if result and result.data:
        return result.data
    return []

def create_quest(quest_data: Dict[str, Any]) -> Optional[str]:
    """
    Create a new quest
    
    Args:
        quest_data: Dictionary with quest fields
        
    Returns:
        ID of the created quest or None if error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
        
    result = safe_supabase_call(
        lambda: supabase_client.table("quests").insert(quest_data).execute(),
        fallback_value=None
    )
    
    if result and result.data and len(result.data) > 0:
        return result.data[0].get('id')
    return None

def fetch_submissions_by_user(user_id: int, quest_id: Optional[Any] = None) -> List[Dict[str, Any]]:
    """
    Fetch all submissions by a user
    
    Args:
        user_id: Telegram user ID
        quest_id: Optional quest ID to filter by
        
    Returns:
        List of submission dictionaries or empty list if none/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return []
    
    # Start with base query
    query = supabase_client.table("submissions").select("*").eq("user_id", user_id)
    
    # Add quest filter if provided
    if quest_id:
        query = query.eq("quest_id", quest_id)
    
    result = safe_supabase_call(
        lambda: query.execute(),
        fallback_value={"data": []}
    )
    
    if result and result.data:
        return result.data
    return []

def fetch_approved_submissions() -> List[Dict[str, Any]]:
    """
    Fetch all approved submissions
    
    Returns:
        List of approved submission dictionaries or empty list if none/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return []
        
    result = safe_supabase_call(
        lambda: supabase_client.table("submissions").select("*").eq("status", "approved").execute(),
        fallback_value={"data": []}
    )
    
    if result and result.data:
        return result.data
    return []

def create_submission(user_id: int, quest_id: Any, message_id: int, caption: str,
                     photo_file_id: Optional[str] = None, video_file_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Create a new submission
    
    Args:
        user_id: Telegram user ID
        quest_id: Quest ID
        message_id: Telegram message ID (not stored in database)
        caption: Caption text from the message
        photo_file_id: Optional Telegram photo file ID
        video_file_id: Optional Telegram video file ID
        
    Returns:
        Created submission data or None if error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
    
    # Determine media type and file ID
    media_type = None
    media_file_id = None
    if photo_file_id:
        media_type = "photo"
        media_file_id = photo_file_id
    elif video_file_id:
        media_type = "video"
        media_file_id = video_file_id
    else:
        logger.error("Submission requires either photo_file_id or video_file_id")
        return None
    
    # Prepare submission data
    from datetime import datetime
    
    submission_data = {
        "user_id": user_id,
        "quest_id": quest_id,
        "media_type": media_type,
        "media_file_id": media_file_id,  # Use the combined field instead of separate photo/video fields
        "caption": caption,
        "submitted_at": datetime.now().isoformat(),
        "status": "pending"
    }
    
    result = safe_supabase_call(
        lambda: supabase_client.table("submissions").insert(submission_data).execute(),
        fallback_value=None
    )
    
    if result and result.data and len(result.data) > 0:
        return result.data[0]
    return None

def update_submission_status(submission_id: Any, status: str, reviewer_data: Dict[str, Any]) -> bool:
    """
    Update submission status
    
    Args:
        submission_id: Submission ID
        status: New status ("approved" or "rejected")
        reviewer_data: Dictionary with reviewer fields
        
    Returns:
        True if successful, False otherwise
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return False
        
    update_data = {"status": status, **reviewer_data}
    
    result = safe_supabase_call(
        lambda: supabase_client.table("submissions").update(update_data).eq("id", submission_id).execute(),
        fallback_value=None
    )
    
    return result is not None and hasattr(result, 'data')

def fetch_badge_image(quest_id: Any) -> Optional[bytes]:
    """
    Fetch a badge image for a quest
    
    Args:
        quest_id: Quest ID
        
    Returns:
        Base64 encoded image data or None if not found/error
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return None
        
    # Try with string conversion first
    result = safe_supabase_call(
        lambda: supabase_client.table("badge_images").select("image_data").eq("quest_id", str(quest_id)).execute(),
        fallback_value={"data": []}
    )
    
    # If no results, try with raw quest_id
    if not result.data or len(result.data) == 0:
        result = safe_supabase_call(
            lambda: supabase_client.table("badge_images").select("image_data").eq("quest_id", quest_id).execute(),
            fallback_value={"data": []}
        )
    
    if result and result.data and len(result.data) > 0 and result.data[0].get("image_data"):
        return result.data[0]["image_data"]
    return None

def update_submission(submission_id: Any, **kwargs) -> bool:
    """
    Update submission data
    
    Args:
        submission_id: ID of the submission to update
        **kwargs: Key-value pairs of fields to update
        
    Returns:
        True if successful, False otherwise
    """
    if not supabase_client:
        logger.error("Supabase client not initialized in db_utils")
        return False
    
    # Remove any None values to avoid nullifying existing values
    update_data = {k: v for k, v in kwargs.items() if v is not None}
    
    if not update_data:
        logger.warning("No valid fields to update for submission")
        return False
    
    result = safe_supabase_call(
        lambda: supabase_client.table("submissions").update(update_data).eq("id", submission_id).execute(),
        fallback_value=None
    )
    
    return result is not None and hasattr(result, 'data') 