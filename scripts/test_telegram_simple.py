import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from telegram import Bot

async def test_send():
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in config/.env")
        return

    print(f"📡 Attempting to send test message to Chat ID: {chat_id}...")
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text="🚀 **Deriv Bot: Test Connection Success!**\nSystem is ready to send trade alerts.")
        print("✅ Message sent successfully! Check your Telegram.")
    except Exception as e:
        print(f"❌ Failed to send message: {e}")

if __name__ == "__main__":
    asyncio.run(test_send())
