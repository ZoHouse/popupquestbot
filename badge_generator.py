from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import textwrap
import math
import io
import logging
import base64

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Add this color dictionary at the top of your file (after imports)
COLOR_THEME = {
    "background": (25, 28, 35, 255),           # Dark background (Will appear white due to mask)
    "border_primary": (75, 85, 180, 255),      # Deep blue
    "border_secondary": (130, 60, 180, 255),   # Rich purple
    "border_tertiary": (60, 100, 200, 255),    # Medium blue
    "logo": (0, 0, 0, 255),                   # Light blue logo -> Changed to Black
    "title": (0, 0, 0, 255),             # White title -> Changed to Black
    "description": (0, 0, 0, 255),       # Light gray description -> Changed to Black
    "label": (0, 0, 0, 255),             # White labels -> Changed to Black
    "value": (0, 0, 0, 255),             # Light gray values -> Changed to Black
    "points_bg": (130, 60, 180, 255),          # Purple points button
    "points_text": (255, 255, 255, 255),       # White points text
    "icon_bg": (40, 45, 55, 255),               # Icon background
}

# Global variables for Supabase client and base URL
supabase_client = None
supabase_url = None

def set_supabase_client(client, base_url=None):
    """Set the Supabase client for use in this module"""
    global supabase_client, supabase_url
    supabase_client = client
    supabase_url = base_url
    logger.info("Supabase client set in badge_generator module")

def create_premium_badge(width, height, border_width=8):
    """Create a premium rounded rectangle badge with subtle gradient border"""
    # Define gradient colors (clockwise from top)
    colors = [
        COLOR_THEME["border_primary"],     # Deep blue
        COLOR_THEME["border_secondary"],   # Rich purple
        COLOR_THEME["border_tertiary"],    # Medium blue
        COLOR_THEME["border_primary"]      # Deep blue again for smoother transition
    ]
    
    # Create base image with shadow for 3D effect
    base = Image.new('RGBA', (width+20, height+20), (0, 0, 0, 0))
    
    # Create the main badge with rounded corners
    badge = Image.new('RGBA', (width, height), COLOR_THEME["background"])
    
    # Create mask for rounded corners
    mask = Image.new('L', (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    corner_radius = 30
    mask_draw.rounded_rectangle([(0, 0), (width, height)], radius=corner_radius, fill=255)
    
    # Apply rounded corners mask - MOVED BACK HERE
    badge.putalpha(mask) 
    
    # Create gradient border
    border = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border)
    
    # Draw border - slightly larger rounded rectangle
    border_outer = Image.new('L', (width, height), 0)
    border_outer_draw = ImageDraw.Draw(border_outer)
    border_outer_draw.rounded_rectangle([(0, 0), (width, height)], radius=corner_radius, fill=255)
    
    # Create inner mask (hollow out the center)
    border_inner = Image.new('L', (width, height), 0)
    border_inner_draw = ImageDraw.Draw(border_inner)
    border_inner_draw.rounded_rectangle(
        [(border_width, border_width), (width-border_width, height-border_width)],
        radius=corner_radius-border_width,
        fill=255
    )
    
    # Calculate gradient positions
    num_segments = len(colors)
    segment_height = height / num_segments
    
    # Draw gradient border segments
    for i, color in enumerate(colors):
        segment = Image.new('RGBA', (width, height), color)
        # Create segment mask
        segment_mask = Image.new('L', (width, height), 0)
        segment_draw = ImageDraw.Draw(segment_mask)
        
        # Draw segment - calculate top and bottom y-coordinates
        top = int(i * segment_height)
        bottom = int((i+1) * segment_height)
        segment_draw.rectangle([(0, top), (width, bottom)], fill=255)
        
        # Apply segment mask
        segment.putalpha(segment_mask)
        border = Image.alpha_composite(border, segment)
    
    # Apply border masks to create hollow border
    border.putalpha(border_outer)
    
    # Create the inner content area (dark background)
    inner = Image.new('RGBA', (width, height), COLOR_THEME["background"])
    inner.putalpha(border_inner)
    
    # Combine border and inner
    combined = Image.alpha_composite(border, inner)
    
    # Add subtle inner shadow/highlight
    inner_highlight = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    highlight_mask = Image.new('L', (width, height), 0)
    highlight_draw = ImageDraw.Draw(highlight_mask)
    highlight_draw.rounded_rectangle(
        [(border_width+2, border_width+2), (width-border_width-2, height-border_width-2)],
        radius=corner_radius-border_width-2,
        fill=255
    )
    # Apply highlight with very slight white glow at top
    highlight_color = (255, 255, 255, 25)  # Very transparent white
    inner_highlight = Image.new('RGBA', (width, height), highlight_color)
    inner_highlight.putalpha(highlight_mask)
    combined = Image.alpha_composite(combined, inner_highlight)
    
    # Apply the main rounded corner mask HERE - REMOVED FROM HERE
    # combined.putalpha(mask)
    
    # Create shadow
    shadow = Image.new('RGBA', (width+20, height+20), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle([(10, 10), (width+10, height+10)], radius=corner_radius, fill=(0, 0, 0, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    
    # Compose final image
    base = Image.alpha_composite(base, shadow)
    # Paste the badge (with mask already applied) onto the base
    base.paste(badge, (10, 10), badge) # Paste badge (already masked) 
    # Then paste the combined border/highlight/inner content ON TOP of the masked badge
    base.paste(combined, (10, 10), combined)
    
    return base, colors

def create_modern_icon(size, border_color=(255, 165, 0)):
    """Create a stylized icon for the badge"""
    icon = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    
    # Draw rounded square background
    draw.rounded_rectangle([(0, 0), (size, size)], radius=size//7, fill=border_color)
    
    # Create image area with mountains
    img_width = int(size * 0.8)
    img_height = int(size * 0.5)
    img_x = int(size * 0.1)
    img_y = int(size * 0.15)
    
    # Blue background for the image area
    draw.rounded_rectangle(
        [(img_x, img_y), (img_x + img_width, img_y + img_height)],
        radius=size//14,
        fill=(100, 200, 255)
    )
    
    # Draw mountains
    mountain_points = [
        (img_x, img_y + img_height),  # Bottom left
        (img_x + img_width * 0.3, img_y + img_height * 0.3),  # First peak
        (img_x + img_width * 0.4, img_y + img_height * 0.5),  # Valley
        (img_x + img_width * 0.7, img_y + img_height * 0.2),  # Second peak (higher)
        (img_x + img_width, img_y + img_height)  # Bottom right
    ]
    draw.polygon(mountain_points, fill=(40, 160, 80))
    
    # Add plus icon in top right
    plus_size = size * 0.18
    plus_x = img_x + img_width * 0.85
    plus_y = img_y + img_height * 0.3
    draw.rectangle([(plus_x - plus_size/2.5, plus_y - plus_size/8), 
                   (plus_x + plus_size/2.5, plus_y + plus_size/8)], 
                   fill=(255, 255, 255))
    draw.rectangle([(plus_x - plus_size/8, plus_y - plus_size/2.5), 
                   (plus_x + plus_size/8, plus_y + plus_size/2.5)], 
                   fill=(255, 255, 255))
    
    # Add subtle barcode lines at bottom
    barcode_y = img_y + img_height + size * 0.15
    for i in range(7):
        line_x = img_x + i * (img_width / 7)
        line_width = img_width / 14
        if i % 2 == 0:
            line_height = size * 0.15
        else:
            line_height = size * 0.1
        
        draw.rectangle(
            [(line_x, barcode_y), (line_x + line_width, barcode_y + line_height)],
            fill=(30, 30, 30)
        )
    
    return icon

def generate_quest_badge(
    title: str,
    description: str,
    action: str,
    deadline: str,
    quest_id: str,
    points: int,
    icon_image: Image.Image | None = None  # Add optional icon_image parameter
) -> io.BytesIO | None:
    """
    Generates a quest badge image with improved text rendering and optional icon.

    Args:
        title (str): Quest title.
        description (str): Quest description.
        action (str): Action text.
        deadline (str): Deadline text.
        quest_id (str): Quest ID (UUID or other).
        points (int): Points value.
        icon_image (Image.Image, optional): A PIL Image object for the icon. Defaults to None.

    Returns:
        io.BytesIO | None: BytesIO object containing the PNG image data, or None if error.
    """
    # Set dimensions - 16:9 aspect ratio for modern feel
    width, height = 800, 500
    border_width = 12
    
    # Convert quest_id to numeric if it's a string with UUID
    display_id = quest_id
    if isinstance(quest_id, str):
        # If quest_id is a UUID, use a shortened version for display
        if '-' in quest_id:
            # For UUID, just use the first part or a hash of it
            display_id = int(hash(quest_id) % 1000)
        else:
            # Try to convert to int if it's a numeric string
            try:
                display_id = int(quest_id)
            except ValueError:
                # If it can't be converted, use a hash
                display_id = int(hash(quest_id) % 1000)
    
    try:
        # Create premium badge with gradient border
        badge, colors = create_premium_badge(width, height, border_width)
        draw = ImageDraw.Draw(badge)
        
        # Load fonts
        try:
            title_font = ImageFont.truetype("fonts/Montserrat-Bold.ttf", 50)  # Reduced from 65
            logo_font = ImageFont.truetype("fonts/Montserrat-ExtraBold.ttf", 65)
            header_font = ImageFont.truetype("fonts/Montserrat-Bold.ttf", 32)
            body_font = ImageFont.truetype("fonts/Montserrat-Medium.ttf", 26)
            small_font = ImageFont.truetype("fonts/Montserrat-Medium.ttf", 24)
            points_font = ImageFont.truetype("fonts/Montserrat-Bold.ttf", 80)
        except IOError:
            logger.error("Failed to load fonts. Make sure the fonts directory exists with required fonts.")
            return None
        
        # Add logo in top left
        draw.text((40, 30), "\\z/", fill=(0, 0, 0, 255), font=logo_font)
        
        # Add quest ID in top right
        id_text = f"Quest ID: {display_id:03d}"
        id_width = draw.textlength(id_text, font=small_font)
        draw.text((width - 40 - id_width, 40), id_text, fill=(0, 0, 0, 255), font=small_font)
        
        # Calculate max width for title to avoid icon overlap
        title_max_width = width - 300  # Leave space for icon
        
        # Process title - limit to 3 words and ensure max 2 lines
        title_words = title.split()[:3]  # Limit to first 3 words
        title = " ".join(title_words)
        
        # Add title with wrapping if needed
        if draw.textlength(title, font=title_font) > title_max_width:
            # Need to wrap the title into max 2 lines
            words = title_words
            lines = []
            current_line = words[0]
            
            for word in words[1:]:
                test_line = current_line + " " + word
                if draw.textlength(test_line, font=title_font) <= title_max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            
            lines.append(current_line)
            lines = lines[:2]  # Ensure max 2 lines
            
            # Draw each line with reduced spacing
            y_pos = 160  # Starting position for title
            for line in lines:
                draw.text((40, y_pos), line, fill=(0, 0, 0, 255), font=title_font)
                y_pos += title_font.size - 5  # Reduced spacing between lines
            
            # Adjust description starting position based on title height
            desc_y = y_pos + 40  # Reduced spacing after title
        else:
            # Single line title
            draw.text((40, 160), title, fill=(0, 0, 0, 255), font=title_font)
            desc_y = 230  # Reduced from 260
        
        # Calculate max width for description to avoid icon overlap
        desc_max_width = width - 60  # 60px padding from left edge
        
        # Truncate description to first 10 words if longer
        desc_words = description.split()
        if len(desc_words) > 10:
            truncated_desc = " ".join(desc_words[:10]) + "..."
            description = truncated_desc
        
        # Add description with proper text wrapping and improved spacing
        wrapped_text = textwrap.wrap(description, width=28)
        for line in wrapped_text:
            draw.text((40, desc_y), line, fill=(0, 0, 0, 255), font=body_font)
            desc_y += 35
        
        # Create info section with improved spacing
        # Ensure min spacing between description and action, but also don't leave too much space
        info_y = max(desc_y + 40, height - 180)  # Reduced from (desc_y + 70, height - 140)
        
        # Add action with improved alignment and clear spacing
        draw.text((40, info_y), "Action:", fill=(0, 0, 0, 255), font=header_font)
        
        # Calculate action text position with more spacing to avoid overlap
        action_width = draw.textlength("Action:", font=header_font)
        action_x = 40 + action_width + 25  # Add 25px spacing between label and value
        
        # Fix alignment issues - use font ascent/descent for proper baseline alignment
        header_ascent = (header_font.getbbox("Action:")[3] - header_font.getbbox("Action:")[1]) * 0.75
        body_ascent = (body_font.getbbox(action)[3] - body_font.getbbox(action)[1]) * 0.75
        action_y_offset = (header_ascent - body_ascent) / 2
        
        # --- Icon and Button Positioning ---
        icon_bg_y = 110 # Default vertical position for icon at the top
        
        # Create a button/pill background for points with purple color
        points_text = str(points)
        points_width = draw.textlength(points_text, font=points_font)
        button_width = points_width + 80
        button_height = 70
        
        # Position button at the bottom right
        button_x = width - button_width - 60  # Right edge padding
        button_y = height - button_height - 50  # Fixed position from bottom
        
        # Calculate maximum width for action text to avoid overlap with points pill
        max_action_width = button_x - action_x - 30  # 30px safe margin
        
        # Wrap action text if it's too long to fit without overlapping the points pill
        if draw.textlength(action, font=body_font) > max_action_width:
            # Break the action text into words and create a wrapped line
            action_words = action.split()
            wrapped_action = []
            current_line = ""
            
            for word in action_words:
                test_line = current_line + " " + word if current_line else word
                if draw.textlength(test_line, font=body_font) <= max_action_width:
                    current_line = test_line
                else:
                    if current_line:
                        wrapped_action.append(current_line)
                        current_line = word
                    else:
                        # If even a single word is too long, truncate it
                        wrapped_action.append(word[:10] + "...")
                        break
            
            if current_line:
                wrapped_action.append(current_line)
            
            # Draw each line of wrapped action text
            action_y = info_y + action_y_offset
            for i, line in enumerate(wrapped_action):
                draw.text((action_x, action_y), line, fill=(0, 0, 0, 255), font=body_font)
                action_y += body_font.size * 0.8  # Reduced line spacing for more compact look
            
            # Update deadline_y based on the last line of action
            deadline_y = action_y + 10  # Reduced spacing between action and deadline
        else:
            # Draw single line action text
            draw.text((action_x, info_y + action_y_offset), action, fill=(0, 0, 0, 255), font=body_font)
            
            # Keep original spacing for deadline if action didn't wrap
            deadline_y = info_y + 40  # Reduced spacing
        
        # Add deadline with proper spacing to avoid overlap
        draw.text((40, deadline_y), "Deadline:", fill=(0, 0, 0, 255), font=header_font)
        
        # Align deadline value with action value
        deadline_width = draw.textlength("Deadline:", font=header_font)
        deadline_x = 40 + deadline_width + 25  # Same spacing as action
        
        # Use the same alignment fix for deadline
        header_ascent = (header_font.getbbox("Deadline:")[3] - header_font.getbbox("Deadline:")[1]) * 0.75
        body_ascent = (body_font.getbbox(deadline)[3] - body_font.getbbox(deadline)[1]) * 0.75
        deadline_y_offset = (header_ascent - body_ascent) / 2
        
        draw.text((deadline_x, deadline_y + deadline_y_offset), deadline, fill=(0, 0, 0, 255), font=body_font)
        
        # Create a more polished button with multiple layers
        # First create a black base with slight transparency for depth
        base_button = Image.new('RGBA', (int(button_width+6), int(button_height+6)), (0, 0, 0, 180))
        base_mask = Image.new('L', (int(button_width+6), int(button_height+6)), 0)
        base_draw = ImageDraw.Draw(base_mask)
        base_draw.rounded_rectangle(
            [(0, 0), (button_width+6, button_height+6)],
            radius=(button_height+6)//2,
            fill=255
        )
        base_button.putalpha(base_mask)
        
        # Create main button with purple color
        button = Image.new('RGBA', (int(button_width), int(button_height)), (0, 0, 0, 0))
        button_mask = Image.new('L', (int(button_width), int(button_height)), 0)
        button_mask_draw = ImageDraw.Draw(button_mask)
        button_mask_draw.rounded_rectangle(
            [(0, 0), (button_width, button_height)],
            radius=button_height//2,
            fill=255
        )
        
        # Purple color with slight gradient
        button_fill = Image.new('RGBA', (int(button_width), int(button_height)), COLOR_THEME["points_bg"])
        button_fill.putalpha(button_mask)
        button = button_fill
        
        # Add subtle shading for depth instead of a white highlight
        shadow = Image.new('RGBA', (int(button_width), int(button_height)), (0, 0, 0, 30))
        shadow_mask = Image.new('L', (int(button_width), int(button_height)), 0)
        shadow_draw = ImageDraw.Draw(shadow_mask)
        shadow_draw.rounded_rectangle(
            [(button_width*0.1, button_height*0.6), (button_width*0.9, button_height*0.95)], 
            radius=button_height//4,
            fill=255
        )
        shadow.putalpha(shadow_mask)
        
        # Composite the shadow onto the button for a subtle depth effect
        button = Image.alpha_composite(button, shadow)
        
        # Add points text with better visibility
        button_draw = ImageDraw.Draw(button)
        text_x = (button_width - points_width) // 2
        text_y = (button_height - points_font.size) // 2 - 5  # Adjustment for visual centering
        
        # Draw main text
        button_draw.text((text_x, text_y), points_text, fill=(255, 255, 255, 255), font=points_font)
        
        # Paste base shadow button
        badge.paste(base_button, (int(button_x-3), int(button_y-3)), base_button)
        
        # Paste the button onto the badge
        badge.paste(button, (int(button_x), int(button_y)), button)
        
        # --- Icon Placement Above Points Pill ---
        if icon_image:
            try:
                # Make icon slightly wider than points button
                target_icon_size = int(button_width * 1.5)   # ~50% wider than the pill

                if icon_image.mode != 'RGBA':
                    icon_image = icon_image.convert('RGBA')

                # Resize icon
                icon_resized = icon_image.copy()
                icon_resized.thumbnail((target_icon_size, target_icon_size), Image.Resampling.LANCZOS)

                # Center horizontally over button
                icon_center_x = button_x + (button_width // 2) - (target_icon_size // 2)
                icon_center_y = button_y - target_icon_size - 20

                # Paste icon
                badge.paste(icon_resized, (int(icon_center_x), int(icon_center_y)), icon_resized)

                logger.info(f"Pasted centered icon above points pill at ({icon_center_x}, {icon_center_y})")
            except Exception as e:
                logger.error(f"Error placing icon: {e}")
        
        # --- Store badge in Supabase ---
        if supabase_client and quest_id:
            try:
                # Save image to BytesIO
                img_buffer = io.BytesIO()
                badge.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Convert to base64 for storage
                img_data = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
                
                # Create data to insert
                badge_data = {
                    "quest_id": str(quest_id),
                    "image_data": img_data
                }
                
                # Check if record exists
                result = supabase_client.table("badge_images").select("*").eq("quest_id", str(quest_id)).execute()
                
                if result.data:
                    # Update existing record
                    supabase_client.table("badge_images").update({"image_data": img_data}).eq("quest_id", str(quest_id)).execute()
                    logger.info(f"Updated badge image in Supabase for quest ID: {quest_id}")
                else:
                    # Insert new record
                    supabase_client.table("badge_images").insert(badge_data).execute()
                    logger.info(f"Inserted badge image into Supabase for quest ID: {quest_id}")
                
                # Return BytesIO for further use
                img_buffer.seek(0)
                return img_buffer
                
            except Exception as e:
                logger.error(f"Error saving badge to Supabase: {e}")
                # Continue to return BytesIO even if Supabase save fails
        
        # --- Finalization ---
        # Save image to a bytes buffer
        img_buffer = io.BytesIO()
        badge.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        logger.info(f"Badge generated successfully for Quest ID: {quest_id}")
        return img_buffer  # Return BytesIO object
    
    except Exception as e:
        logger.error(f"Error generating badge: {e}")
        return None

# Example usage
if __name__ == "__main__":
    import icon_provider # Import icon provider for icons
    
    # Get a sample icon
    sample_icon = None
    try:
        # Try to get a category icon
        all_icons = icon_provider.get_all_categories()
        if all_icons:
            sample_icon_category_id = all_icons[0]['id'] # Get the first available icon category
            sample_icon = icon_provider.get_icon_by_category(sample_icon_category_id)
            print(f"Using sample icon: {sample_icon_category_id}")
        else:
            # If categories are empty, try a default icon
            print("No icon categories found, attempting default icon.")
            try:
                sample_icon = icon_provider.get_default_icon() # Assuming this function exists
            except:
                print("Default icon not available.")
    except Exception as e:
        print(f"Error getting sample icon: {e}")
    
    # Generate a sample badge
    badge_buffer = generate_quest_badge(
        title="Meet Samurai",
        description="Take a selfie with samurai at Zo House.",
        action="Photo on the telegram group",
        deadline="2025-05-04",
        quest_id=1,
        points=420,
        icon_image=sample_icon # Use the loaded icon
    )
    
    # Save the badge to a file
    if badge_buffer:
        try:
            with open("sample_badge.png", "wb") as f:
                f.write(badge_buffer.getvalue())
            print("Badge generated and saved as sample_badge.png successfully!")
        except Exception as e:
            print(f"Error saving badge to file: {e}")
    else:
        print("Failed to generate badge.") 