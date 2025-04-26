import asyncio
import logging
import os
import time
import random
import requests
import re
from nio import AsyncClient, RoomMessageText, SyncResponse
from openai import AsyncOpenAI, RateLimitError

# Get environment variables for sensitive information
MATRIX_SERVER = os.environ.get("MATRIX_SERVER", "https://matrix.org")
MATRIX_USER = os.environ.get("MATRIX_USER", "@steely-dan:matrix.org")
MATRIX_PASSWORD = os.environ.get("MATRIX_PASSWORD")
MATRIX_ROOM_ALIAS = os.environ.get("MATRIX_ROOM_ALIAS", "#Bots_sdc2:matrix.org")

# OpenAI configuration from environment variables
BOT_OPENAI_API_KEY = os.environ.get("BOT_OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-nano")

PARTICLE_DEVICE_ID = os.environ.get("PARTICLE_DEVICE_ID")
PARTICLE_ACCESS_TOKEN = os.environ.get("PARTICLE_ACCESS_TOKEN")
PARTICLE_FUNCTION_NAME = os.environ.get("PARTICLE_FUNCTION_NAME", "timerExpired")


# System prompt from environment variable with a default
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", """
You are a lighthearted chatbot. Respond specifically if the user says anything about setting a timer, or even mentions what 
sounds like a time duration with this JSON (and nothing else)

{"time":<integer which is the time in seconds}

For example, the response to 'set timer for 15 minutes' would be

{"time":900}

If the message has nothing to do with time or timer, just say something friendly.
""")

# Check for required environment variables
required_vars = {
    "MATRIX_PASSWORD": MATRIX_PASSWORD,
    "BOT_OPENAI_API_KEY": BOT_OPENAI_API_KEY
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Matrix client setup
client = AsyncClient(MATRIX_SERVER, MATRIX_USER)

# OpenAI client setup
openai_client = AsyncOpenAI(api_key=BOT_OPENAI_API_KEY)

# Rate limiting variables
last_api_call = 0
min_delay_between_calls = 3.0  # Increased to 3 seconds minimum between calls
jitter = 2.0  # Add random jitter of up to 2 seconds to avoid synchronized calls

# Track the last event timestamp we've seen to ignore historical messages
# This will be set to the current time after the initial sync
initial_sync_done = False
connection_timestamp = 0

# Add a flag to track if we're in cooldown mode after hitting rate limits
in_cooldown = False
cooldown_until = 0
cooldown_period = 60  # 1 minute cooldown after hitting rate limits

# Dictionary to store active timers
active_timers = {}

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def call_particle_function(argument="triggered"):
    """Call the function on the Particle device"""
    if not PARTICLE_DEVICE_ID or not PARTICLE_ACCESS_TOKEN:
        logger.warning("Particle device ID or access token not set, skipping function call")
        return False
    
    try:
        logger.info(f"Calling Particle function '{PARTICLE_FUNCTION_NAME}' on device {PARTICLE_DEVICE_ID}")
        
        url = f"https://api.particle.io/v1/devices/{PARTICLE_DEVICE_ID}/{PARTICLE_FUNCTION_NAME}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "access_token": PARTICLE_ACCESS_TOKEN,
            "arg": argument
        }
        
        response = requests.post(url, headers=headers, data=data)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Particle function call successful, returned: {result.get('return_value', 'No return value')}")
            return True
        else:
            logger.error(f"Error calling Particle function: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Exception calling Particle function: {str(e)}")
        return False


async def timer_handler(room_id, timer_id):
    """Function to be called when timer expires"""
    global active_timers
    
    logger.info(f"Timer {timer_id} expired for room {room_id}!")
    
    if timer_id in active_timers:
        del active_timers[timer_id]
    

    # Call the Particle function
    particle_result = call_particle_function()
    # Send a message to the room
    if room_id:
        try:
            await client.room_send(
                room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": "Timer expired!"}
            )
            logger.info(f"Sent timer expiration message to room {room_id}")
        except Exception as e:
            logger.error(f"Error sending timer expiration message: {e}")

def set_timer(seconds, room_id):
    """Set a timer that will call timer_handler after specified seconds"""
    timer_id = f"timer_{int(time.time())}_{random.randint(1000, 9999)}"
    logger.info(f"Setting timer {timer_id} for {seconds} seconds in room {room_id}")
    
    # Create an async task to handle the timer
    async def timer_task():
        await asyncio.sleep(seconds)
        await timer_handler(room_id, timer_id)
    
    # Schedule the timer task
    task = asyncio.create_task(timer_task())
    
    # Store the task
    active_timers[timer_id] = task
    
    return timer_id

async def get_ai_response(user_message):
    """Get a response from the OpenAI API with improved rate limiting and error handling."""
    global last_api_call, in_cooldown, cooldown_until
    
    now = time.time()
    
    # Check if we're in cooldown mode
    if in_cooldown and now < cooldown_until:
        remaining = int(cooldown_until - now)
        return f"I'm currently in cooldown mode due to rate limiting. Please try again in {remaining} seconds."
    else:
        in_cooldown = False
    
    # Implement rate limiting with jitter
    time_since_last_call = now - last_api_call
    required_delay = min_delay_between_calls + random.uniform(0, jitter)
    
    if time_since_last_call < required_delay:
        wait_time = required_delay - time_since_last_call
        logging.info(f"Rate limiting: Waiting {wait_time:.2f} seconds before API call")
        await asyncio.sleep(wait_time)
    
    # Update last call time
    last_api_call = time.time()
    
    # Try to get response with exponential backoff
    max_retries = 5
    retry_delay = 2  # Increased initial delay
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Attempt {attempt+1}/{max_retries} to call OpenAI API")
            response = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ]
            )
            return response.choices[0].message.content
        
        except RateLimitError as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 2)  # Exponential backoff with jitter
                logging.warning(f"Rate limit hit. Waiting {wait_time:.2f} seconds before retry.")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"Rate limit exceeded after {max_retries} attempts: {e}")
                # Enter cooldown mode
                in_cooldown = True
                cooldown_until = time.time() + cooldown_period
                return "I've hit the API rate limit. I'm entering cooldown mode for 1 minute to avoid further rate limiting. Please try again later."
        
        except Exception as e:
            logging.error(f"Error getting AI response: {e}")
            return f"Sorry, I couldn't process that request due to an API error: {str(e)}"

async def message_callback(room, event):
    global connection_timestamp, initial_sync_done
    
    # Skip processing if initial sync isn't done
    if not initial_sync_done:
        logger.info("Initial sync not complete, skipping message")
        return
    
    # Get event timestamp (milliseconds to seconds)
    event_timestamp = event.server_timestamp / 1000
    
    # Skip if this is an old message or from the bot itself
    if event.sender == client.user_id:
        logger.info(f"Skipping message from self: {event.body}")
        return
    
    if event_timestamp <= connection_timestamp:
        logger.info(f"Skipping old message from {event.sender}: {event.body}")
        logger.info(f"Message timestamp: {event_timestamp}, Connection timestamp: {connection_timestamp}")
        return
    
    logger.info(f"Processing new message in {room.room_id} from {event.sender}: {event.body}")
    
    # Get response from OpenAI
    response = await get_ai_response(event.body)
    
    # Check if the response is a timer request (matching {"time":X})
    timer_match = re.match(r'^\s*{"time":(\d+)}\s*$', response)
    if timer_match:
        try:
            # Extract timer duration
            timer_seconds = int(timer_match.group(1))
            
            # Set the timer
            timer_id = set_timer(timer_seconds, room.room_id)
            
            # Send message about timer creation
            formatted_time = format_time_duration(timer_seconds)
            response = f"Timer set for {formatted_time}. I'll notify you when it expires."
            
            logger.info(f"Created timer for {timer_seconds} seconds with ID {timer_id}")
        except Exception as e:
            logger.error(f"Error processing timer: {e}")
            response = f"I couldn't set the timer. Error: {str(e)}"
    
    # Send the response back to the Matrix room
    await client.room_send(
        room.room_id,
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": response}
    )
    logging.info(f"Sent response: {response}")

def format_time_duration(seconds):
    """Format seconds into a human-readable time duration"""
    return f"{seconds} seconds"

async def sync_callback(response):
    """Update the initial sync status when we receive a sync"""
    global initial_sync_done, connection_timestamp
    
    if isinstance(response, SyncResponse) and response.next_batch and not initial_sync_done:
        # Mark the initial sync as complete and set connection timestamp
        initial_sync_done = True
        connection_timestamp = time.time()
        logger.info(f"INITIAL SYNC COMPLETE. Setting connection_timestamp to {connection_timestamp}")
        logger.info("Bot will now only respond to new messages from this point forward.")

async def main():
    global initial_sync_done, connection_timestamp
    
    # Add a startup delay to ensure any previous rate limits have cleared
    startup_delay = random.uniform(5, 10)
    logging.info(f"Starting up with initial delay of {startup_delay:.2f} seconds to avoid rate limits")
    await asyncio.sleep(startup_delay)
    
    login_response = await client.login(MATRIX_PASSWORD)
    if hasattr(login_response, "user_id"):
        client.user_id = login_response.user_id
        logging.info(f"Logged in as: {client.user_id}")
    else:
        logging.error("Login failed")
        return

    join_response = await client.join(MATRIX_ROOM_ALIAS)
    logging.debug(f"Join response: {join_response}")
    if hasattr(join_response, "room_id"):
        logging.info(f"Joined room: {MATRIX_ROOM_ALIAS} (room id: {join_response.room_id})")
    else:
        logging.error(f"Failed to join room: {MATRIX_ROOM_ALIAS}. Check if the room is public or if you need an invite.")

    # Register callbacks
    client.add_event_callback(message_callback, RoomMessageText)
    client.add_response_callback(sync_callback)
    
    # Do an initial sync to get caught up with the room state
    logger.info("Starting initial sync - this will establish our message timestamp cutoff")
    initial_sync = await client.sync(timeout=30000)
    
    # Force setting these values in case the sync callback doesn't trigger
    if not initial_sync_done:
        initial_sync_done = True
        connection_timestamp = time.time()
        logger.info(f"Setting connection_timestamp to {connection_timestamp} after manual sync")
    
    # Send a startup message to the room
    room_id = join_response.room_id
    await client.room_send(
        room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text", 
            "body": "Bot is now online and ready to chat! I'll only respond to messages sent after this point."
        }
    )
    
    logger.info("Bot started. Waiting for messages...")
    await client.sync_forever(timeout=30000)

if __name__ == "__main__":
    asyncio.run(main())