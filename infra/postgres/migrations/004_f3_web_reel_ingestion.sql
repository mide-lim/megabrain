-- F3.1 Web Reel ingestion compatibility.

ALTER TABLE app.reels
    ALTER COLUMN telegram_chat_id DROP NOT NULL,
    ALTER COLUMN telegram_user_id DROP NOT NULL,
    ALTER COLUMN telegram_message_id DROP NOT NULL;
