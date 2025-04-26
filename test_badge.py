import badge_generator
import icon_provider

# Try to get a sample icon from the Sports category (which appears in the screenshot)
sample_icon = None
try:
    # Get the icon from the Sports category
    sample_icon = icon_provider.get_icon_by_category("Sports")
    print(f"Loaded Sports icon successfully")
except Exception as e:
    print(f"Error loading Sports icon: {e}")
    # Fallback to any available icon
    try:
        all_icons = icon_provider.get_all_categories()
        if all_icons:
            sample_icon_category_id = all_icons[0]['id']
            sample_icon = icon_provider.get_icon_by_category(sample_icon_category_id)
            print(f"Using fallback icon: {sample_icon_category_id}")
    except Exception as e:
        print(f"Error loading fallback icon: {e}")

# Generate test badge
badge_buffer = badge_generator.generate_quest_badge(
    title="Zo Zo",
    description="ZO ZO ZO",
    action="Photo",
    deadline="ZO O Zo Z",
    quest_id=209,  # Match the ID in the screenshot
    points=111,    # Match the points in the screenshot
    icon_image=sample_icon
)

# Save the badge to a file
if badge_buffer:
    with open("test_badge.png", "wb") as f:
        f.write(badge_buffer.getvalue())
    print("Test badge generated and saved as test_badge.png")
else:
    print("Failed to generate test badge") 