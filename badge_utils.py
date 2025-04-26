import logging
import base64
import io
from typing import Dict, Any, Optional
from PIL import Image

# Import existing modules
import db_utils
import badge_generator
import icon_provider

# Setup logger
logger = logging.getLogger(__name__)

def generate_and_store_badge(quest_data: Dict[str, Any], icon_category: Optional[str] = None, quest_id: Optional[str] = None) -> Optional[io.BytesIO]:
    """
    Generate a badge for a quest and store it in the database
    
    Args:
        quest_data: Dictionary with quest data (title, description, etc.)
        icon_category: Category ID for the icon to use
        quest_id: Quest ID (if already created)
        
    Returns:
        BytesIO buffer containing the generated badge image or None if failed
    """
    try:
        # Get the icon if a category was provided
        icon = None
        if icon_category:
            logger.info(f"Loading icon for category: {icon_category}")
            icon = icon_provider.get_icon_by_category(icon_category)
            
            if icon is None:
                logger.error(f"Failed to load icon for category: {icon_category}")
                # Try to load default icon
                icon = icon_provider.get_icon_by_category("default")
                if icon is None:
                    logger.error("Failed to load default icon")
        
        # Create a temporary quest ID for preview generation if none provided
        badge_quest_id = quest_id or f"preview_{hash(quest_data.get('title', 'untitled'))}"
        
        # Extract required fields
        title = quest_data.get("title", "")
        description = quest_data.get("description", "")
        action = quest_data.get("validation_type", "")
        deadline = quest_data.get("deadline", "")
        points = quest_data.get("points", 0)
        
        # Generate badge
        logger.info(f"Generating badge for quest: {title}")
        badge_buffer = badge_generator.generate_quest_badge(
            title, description, action, deadline, badge_quest_id, points, icon
        )
        
        if badge_buffer is None:
            logger.error("Badge generation failed")
            return None
            
        # If we have a real quest ID, store the badge in the database
        if quest_id:
            logger.info(f"Storing badge for quest ID: {quest_id}")
            
            try:
                # Get image data as base64
                badge_buffer.seek(0)
                image_data = base64.b64encode(badge_buffer.getvalue()).decode('utf-8')
                
                # Store in database
                badge_data = {
                    "quest_id": str(quest_id),
                    "image_data": image_data
                }
                
                db_utils.safe_supabase_call(
                    lambda: db_utils.supabase_client.table("badge_images").insert(badge_data).execute()
                )
                
                logger.info(f"Badge stored for quest ID: {quest_id}")
            except Exception as e:
                logger.error(f"Error storing badge in database: {e}")
                # Continue since we still have the badge in memory
        
        # Return badge buffer positioned at the beginning
        badge_buffer.seek(0)
        return badge_buffer
        
    except Exception as e:
        logger.error(f"Error in generate_and_store_badge: {e}")
        return None

def fetch_badge_for_quest(quest_id: Any) -> Optional[io.BytesIO]:
    """
    Fetch a badge image for a quest from the database
    
    Args:
        quest_id: Quest ID
        
    Returns:
        BytesIO buffer containing the badge image or None if not found/error
    """
    try:
        # Get badge image data from database
        logger.info(f"Fetching badge for quest ID: {quest_id}")
        image_data = db_utils.fetch_badge_image(quest_id)
        
        if image_data:
            # Decode base64 image data
            img_data = base64.b64decode(image_data)
            img_buffer = io.BytesIO(img_data)
            img_buffer.seek(0)
            return img_buffer
            
        # Check if quest has an image_file_id as fallback
        quest = db_utils.fetch_quest(quest_id)
        if quest and quest.get('image_file_id'):
            logger.info(f"Badge not found, using image_file_id: {quest['image_file_id']}")
            return quest['image_file_id']  # Not a BytesIO but handled by caller
            
        logger.warning(f"No badge found for quest ID: {quest_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching badge for quest: {e}")
        return None

def resize_image(img: Image.Image, max_width: int = 800, max_height: int = 600) -> Image.Image:
    """
    Resize an image while maintaining aspect ratio
    
    Args:
        img: PIL.Image to resize
        max_width: Maximum width
        max_height: Maximum height
        
    Returns:
        Resized PIL.Image
    """
    if img.width <= max_width and img.height <= max_height:
        return img  # No need to resize
        
    # Calculate new dimensions
    ratio = min(max_width / img.width, max_height / img.height)
    new_width = int(img.width * ratio)
    new_height = int(img.height * ratio)
    
    # Resize
    return img.resize((new_width, new_height), Image.LANCZOS) 