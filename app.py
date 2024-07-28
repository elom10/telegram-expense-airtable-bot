import logging
from decimal import Decimal
from typing import Union, Dict
from datetime import datetime

import requests
from telegram import (
    ReplyKeyboardMarkup, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

CHOOSING, TYPING_REPLY, TYPING_CHOICE, TYPING_APT = range(4)

reply_keyboard = [
    ["Name of Expense", "Expense Type"],
    ["Amount in GHS", "Notes", "Apt"],
    ["Done"],
]
markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)

expense_types = [
    "Electric", "Water", "Internet", "DSTV", "Cleaning Supplies",
    "Home Repairs and Maintenance", "HOA Service Charge", "Insurance"
]

apt_options = [
    ("Option 103", "103"),
    ("Option 108", "108")
]

def facts_to_str(user_data: Dict[str, str]) -> str:
    """Helper function for formatting the gathered user info."""
    facts = [f"{key} - {value}" for key, value in user_data.items()]
    return "\n".join(facts).join(["\n", "\n"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask user for input."""
    await update.message.reply_text(
        "Hi! My name is Dilligent your expense Botter. I will update airtables with your expenses. "
        "Why don't you tell me what you have spent on?",
        reply_markup=markup,
    )

    return CHOOSING

async def regular_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user choice and provide appropriate input request."""
    text = update.message.text
    if text == "Expense Type":
        return await expense_type_choice(update, context)  # Redirect to expense type selection
    if text == "Apt":
        return await apt_choice(update, context)  # Redirect to Apt selection
    
    context.user_data["choice"] = text
    await update.message.reply_text(f"Your {text.lower()}? Yes, I would love to hear about that!")

    return TYPING_REPLY

async def expense_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display a list of predefined expense types for the user to choose from."""
    keyboard = [[InlineKeyboardButton(expense, callback_data=expense)] for expense in expense_types]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Please choose an expense type from the list below:",
        reply_markup=reply_markup
    )

    return TYPING_CHOICE

async def expense_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle expense type selection from the inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    selected_expense_type = query.data
    context.user_data["Expense Type"] = selected_expense_type
    
    # Inform the user that the expense type has been set and show the summary
    summary_text = (
        "You selected the expense type: {selected_expense_type}.\n\n"
        "Neat! Just so you know, this is what you already told me:\n"
        f"{facts_to_str(context.user_data)}"
        "You can tell me more, or change your opinion on something."
    )
    
    await query.message.reply_text(
        summary_text.format(selected_expense_type=selected_expense_type),
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )

    return CHOOSING

async def apt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display a list of Apt options for the user to choose from."""
    keyboard = [[InlineKeyboardButton(name, callback_data=value)] for name, value in apt_options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Please choose an Apt option from the list below:",
        reply_markup=reply_markup
    )

    return TYPING_APT

async def apt_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Apt selection from the inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    selected_apt = query.data
    context.user_data["Apt"] = selected_apt
    
    # Inform the user that the Apt has been set and show the summary
    summary_text = (
        "You selected the Apt: {selected_apt}.\n\n"
        "Neat! Just so you know, this is what you already told me:\n"
        f"{facts_to_str(context.user_data)}"
        "You can tell me more, or change your opinion on something."
    )
    
    await query.message.reply_text(
        summary_text.format(selected_apt=selected_apt),
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )

    return CHOOSING

async def received_information(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store info provided by user and ask for the next category."""
    user_data = context.user_data
    text = update.message.text
    choice = user_data.get("choice", None)
    
    if choice:
        user_data[choice] = text
        del user_data["choice"]
    
        await update.message.reply_text(
            "Neat! Just so you know, this is what you already told me:"
            f"{facts_to_str(user_data)}You can tell me more, or change your opinion"
            " on something.",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
        )
    else:
        await update.message.reply_text(
            "I didn't receive the category. Please try again.",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
        )
        
    return CHOOSING

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display the gathered info, convert amount to USD, and end the conversation."""
    user_data = context.user_data
    if "choice" in user_data:
        del user_data["choice"]

    # Prepare data for conversion
    name = user_data.get("Name of Expense", "Unknown")
    expense_type = user_data.get("Expense Type", "Uncategorized")
    amount_str = user_data.get("Amount in GHS", "0")
    notes = user_data.get("Notes", "")
    apt = user_data.get("Apt", "108")  # Default to "108" if Apt is not provided
    
    try:
        amount_ghs = Decimal(amount_str)
    except:
        amount_ghs = Decimal(0)

    # Convert amount to USD
    exchange_rate = await get_exchange_rate()
    amount_usd = amount_ghs * Decimal(exchange_rate)

    # Call update_airtable function
    response = await update_airtable(name, expense_type, amount_usd, notes, apt)
    
    # Print the data for debugging
    logger.info(f"Data sent to Airtable: Name: {name}, Expense Type: {expense_type}, Amount (USD): {amount_usd}, Notes: {notes}, Apt: {apt}")
    logger.info(f"Airtable response: {response}")

    # Check if the response indicates success
    if "records" in response and len(response["records"]) > 0 and "id" in response["records"][0]:
        await update.message.reply_text("Successfully updated Airtable!")
    else:
        await update.message.reply_text("Failed to update Airtable. Please try again later.")

    user_data.clear()
    return ConversationHandler.END

async def get_exchange_rate() -> float:
    """Fetch the current exchange rate from GHS to USD."""
    url = "https://api.exchangerate-api.com/v4/latest/GHS"
    response = requests.get(url)
    data = response.json()
    return data["rates"].get("USD", 1.0)  # Default to 1.0 if USD rate not found

async def update_airtable(name: str, expense_type: str, expense: Union[Decimal, float], notes: str, apt: str) -> dict:
    # Determine the URL based on the value of `apt`
    if apt == "108":
        url = "https://api.airtable.com/v0/appT4yGhNwVtyB8jR/Income%20%26%20Expenses"
    elif apt == "103":
        url = "https://api.airtable.com/v0/appqfgm6p6MSGLfI3/Income%20%26%20Expenses"
    else:
        raise ValueError("Invalid apt value")

    headers = {
        "Authorization": "Bearer Bearer",  # Replace with your actual API key
        "Content-Type": "application/json"
    }
    
    current_month = datetime.now().strftime("%B")  # Get the current month as a full month name
    current_year = datetime.now().year  # Get the current year
    current_date = datetime.now().strftime("%Y-%m-%d")  # Get the current date in YYYY-MM-DD format

    data = {
        "records": [
            {
                "fields": {
                    "Name": name,
                    "Month": current_month,
                    "Category": expense_type,
                    "Expense": float(expense),
                    "Notes": notes,
                    # "Year": current_year,
                    "Date": current_date
                }
            }
        ],
        "typecast": True
    }

    # Print the URL and data for debugging purposes
    print(f"URL being used: {url}")
    print("Data being sent to Airtable:", data)

    response = requests.post(url, headers=headers, json=data, timeout=10)
    response.raise_for_status()
    response_json = response.json()
    
    return response_json

def main() -> None:
    """Run the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token("Your_token").build()

    # Add conversation handler with the states CHOOSING, TYPING_CHOICE, TYPING_REPLY, and TYPING_APT
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [
                MessageHandler(
                    filters.Regex("^(Name of Expense|Expense Type|Amount in GHS|Notes|Apt)$"), regular_choice
                ),
            ],
            TYPING_CHOICE: [
                CallbackQueryHandler(expense_type_selected)
            ],
            TYPING_APT: [
                CallbackQueryHandler(apt_selected)
            ],
            TYPING_REPLY: [
                MessageHandler(
                    filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")),
                    received_information,
                ),
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^Done$"), done)],
    )

    application.add_handler(conv_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
