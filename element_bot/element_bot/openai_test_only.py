import os
import logging
import time
from openai import OpenAI  # Changed to synchronous client for simplicity

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get OpenAI API key from environment
api_key = os.environ.get("BOT_OPENAI_API_KEY")
if not api_key:
    raise EnvironmentError("Missing required environment variable: BOT_OPENAI_API_KEY")

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

# System prompt
SYSTEM_PROMPT = """
You are a helpful and friendly assistant in a Matrix chat room.
Be concise, informative, and engaging in your responses.
"""

def test_openai_call(message="Hi there, can you help me?"):
    """Simple function to test OpenAI API call"""
    logger.info("Starting OpenAI API test")
    
    try:
        # Add a small delay before making the call
        time.sleep(1)
        
        # Make the API call
        logger.info(f"Sending request to OpenAI API with message: {message}")
        start_time = time.time()
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message}
            ]
        )
        
        elapsed_time = time.time() - start_time
        logger.info(f"API call completed in {elapsed_time:.2f} seconds")
        
        # Extract and return the response content
        content = response.choices[0].message.content
        logger.info(f"Response received: {content[:50]}...")
        return content
        
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {str(e)}")
        return f"Error: {str(e)}"

if __name__ == "__main__":
    user_message = "Hi my friend convert 'set timer for ten minutes 3 seconds' into python code to wait for that period"
    result = test_openai_call(user_message)
    print("\n--- RESULT ---\n")
    print(result)
    print("\n--------------")