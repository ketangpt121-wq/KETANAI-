import os
import threading
import telebot
from flask import Flask
from openai import OpenAI

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Initialize Telegram Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Initialize OpenAI client pointing to Hugging Face router
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

# Basic Flask route for Render health check
@app.route('/')
def index():
    return "Telegram Bot is running!", 200

# Handle /start and /help commands
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Hello! Send me any message and I'll respond using DeepSeek-R1 via Hugging Face.")

# Handle all other messages
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.send_chat_action(message.chat.id, 'typing')
    
    try:
        # Call the API using the provided snippet translated to Python
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-R1:novita",
            messages=[
                {
                    "role": "user",
                    "content": message.text,
                },
            ],
            stream=False, # Set to False for simpler message handling in Telegram
        )
        
        # Get the reply content
        reply = response.choices[0].message.content
        bot.reply_to(message, reply)
        
    except Exception as e:
        bot.reply_to(message, f"An error occurred: {str(e)}")

def run_bot():
    """Run the Telegram bot polling process."""
    if TELEGRAM_BOT_TOKEN:
        print("Starting Telegram bot polling...")
        bot.infinity_polling()
    else:
        print("Warning: TELEGRAM_BOT_TOKEN not set. Bot polling will not start.")

if __name__ == "__main__":
    # Start bot polling in a background thread 
    # so Flask can run and bind to the port expected by Render.com
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Start the Flask web server
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
