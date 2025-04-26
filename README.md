# DXBxZo Quest Telegram Bot

This is a Telegram bot designed to manage quests, track user points, handle submissions, and facilitate community engagement for the DXBxZo community.

## Features

*   **User Registration:** New users are prompted to register their EVM wallet address.
*   **Quest Management (Admin):**
    *   Create new quests with titles, descriptions, categories, points, deadlines, validation types (photo, video, text), and keywords.
    *   Optionally attach images to quests via upload or AI generation.
    *   Announce new quests to the public group.
*   **Quest Participation (User):**
    *   View available quests (`/viewquests`) with pagination.
    *   View details of a specific quest.
    *   Submit quest completions via photo/video with a specific keyword in the caption.
*   **Submission Review (Admin):**
    *   Submissions are forwarded to an admin group.
    *   Admins can approve or reject submissions.
    *   Approved submissions automatically update user points.
*   **Leaderboard:** Display the top users based on accumulated points (`/leaderboard`).
*   **User Info (Admin):** View details about a specific user's points and submissions (`/tripper`).
*   **Wallet Management:** Users can update their registered wallet address (`/updatewallet`).
*   **Badge Generation:**
    *   Generates standard image badges for quests.
    *   Includes experimental AI-powered badge generation.
*   **Supabase Integration:** Uses Supabase for database storage (users, quests, submissions, badges).
*   **Webhook Support:** Runs via webhook for efficient updates.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
2.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Set up Environment Variables:**
    Create a `.env` file in the root directory and add the following variables:

    ```env
    # --- Required Variables ---
    SUPABASE_URL="your_supabase_url"                             # URL for your Supabase project
    SUPABASE_KEY="your_supabase_service_role_key"                # Service Role Key for Supabase (keep this secret!)
    TELEGRAM_BOT_TOKEN="your_telegram_bot_token"                 # Token for your Telegram Bot from BotFather
    ADMIN_GROUP_ID="your_admin_telegram_group_id"                # Numeric ID of the Telegram group for admin commands/approvals
    PUBLIC_GROUP_ID="your_public_telegram_group_id"              # Numeric ID of the Telegram group for quest announcements/submissions
    WEBHOOK_URL="your_publicly_accessible_webhook_url"           # Public HTTPS URL where the bot will receive updates (e.g., from Render)
    PORT="8443"                                                  # Port the webhook server will listen on (provided by deployment platform like Render)

    # --- Optional Variables ---
    # HUGGINGFACE_API_KEY="your_huggingface_api_key"               # Required ONLY if using the AI Badge Generation feature
    ```

5.  **Set up Supabase:**
    *   Create a Supabase project.
    *   Create the necessary tables (`users`, `quests`, `submissions`, `badge_images`) and storage buckets (`quest_images`). Ensure appropriate policies are set.
    *   Add the `SUPABASE_URL` and `SUPABASE_KEY` to your `.env` file.

## Running the Bot

```bash
python zo_quest_bot.py
```

The bot uses a webhook, so it needs to be deployed to a server or platform (like Render, Heroku, etc.) that can receive incoming HTTPS requests.

## Available Commands

**User Commands:**

*   `/start`: Register or welcome message. Prompts for wallet if needed.
*   `/viewquests`: Show available quests.
*   `/leaderboard`: Show the top users.
*   `/updatewallet`: (Private Chat) Start the process to change the registered wallet address.

**Admin Commands (in Admin Group only):**

*   `/newquest`: Start the interactive process to create a new quest.
*   `/tripper <user_id/@username>`: Show information about a specific user.

**Quest Submission (in Public Group):**

*   Send a photo or video with the quest keyword (e.g., `zozozo123`) in the caption.

## Dependencies

*   `python-telegram-bot[ext]`
*   `supabase`
*   `python-dotenv`
*   `pytz`
*   `requests`
*   `Pillow` (Likely needed by badge generators)
*   `numpy` (Likely needed by badge generators)
*   `transformers` (Optional, for AI badge generation)
*   `diffusers` (Optional, for AI badge generation)
*   `torch` (Optional, for AI badge generation)

*(See `requirements.txt` for specific versions)*

## Badge Generator

The bot includes an automatic badge generator for quests. Each time a new quest is created:

1. A visually appealing badge is generated with the quest details
2. The badge is stored in the Supabase database as base64-encoded image data
3. The badge is used when announcing the quest to the community

### Badge Generation Options

When creating a quest, you have two options for badge images:

1. **Upload**: Upload a custom image for the quest
2. **AI Generate**: Create a professionally-designed badge with an AI-generated icon customized to your quest description

The AI-generated badges use Hugging Face's Stable Diffusion models to create unique, professional 3D icons that represent your quest's theme. These icons are then composited onto the badge template.

### Viewing Badges

To view the badges that have been generated, you can use the `view_badges.py` script, which will:

1. Download up to 5 random badge samples from the database
2. Save them locally in the `badge_samples` directory for inspection
3. Display the file paths of the saved badges

```python view_badges.py
```

## Database Schema

The project uses Supabase as its database with the following table structure:

### Users Table
Stores user information and points:
- `id` (TEXT): Primary key, unique identifier
- `username` (TEXT): Unique username
- `wallet_address` (TEXT): User's wallet address
- `points` (INTEGER): Total points earned
- `created_at` (TIMESTAMP): Account creation time

### Quests Table
Stores quest information:
- `id` (UUID): Primary key
- `title` (TEXT): Quest title
- `description` (TEXT): Quest description
- `action` (TEXT): Required action to complete
- `deadline` (TIMESTAMP): Quest completion deadline
- `points` (INTEGER): Points awarded for completion
- `active` (BOOLEAN): Whether quest is active
- `keyword` (TEXT): Unique keyword for quest identification
- `created_at` (TIMESTAMP): Creation time
- `updated_at` (TIMESTAMP): Last update time

### Submissions Table
Tracks quest submissions by users:
- `id` (UUID): Primary key
- `user_id` (TEXT): Foreign key to users
- `quest_id` (UUID): Foreign key to quests
- `status` (TEXT): Submission status (pending/approved)
- `created_at` (TIMESTAMP): Submission time
- `updated_at` (TIMESTAMP): Last status update time

### Badge Images Table
Stores quest badge images:
- `quest_id` (UUID): Primary key, foreign key to quests
- `image_data` (TEXT): Base64-encoded badge image
- `created_at` (TIMESTAMP): Creation time
- `updated_at` (TIMESTAMP): Last update time

### Relationships
- Each user can have multiple submissions
- Each quest can have multiple submissions
- Each quest has one badge image
- Each submission belongs to one user and one quest

### Indexes
- `idx_quests_active`: For filtering active quests
- `idx_quests_keyword`: For looking up quests by keyword
- `idx_submissions_user_status`: For filtering user submissions by status

## Maintenance

- Regularly check the Telegram bot logs for errors
- Monitor Supabase database growth and size of badge_images table
- Consider periodic cleanup of old submissions and unused badge images 