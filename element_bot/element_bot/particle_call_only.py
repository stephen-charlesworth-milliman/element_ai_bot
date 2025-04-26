import asyncio
import logging
import os
import time
import random
import requests

PARTICLE_DEVICE_ID = os.environ.get("PARTICLE_DEVICE_ID")
PARTICLE_ACCESS_TOKEN = os.environ.get("PARTICLE_ACCESS_TOKEN")
PARTICLE_FUNCTION_NAME = os.environ.get("PARTICLE_FUNCTION_NAME", "timerExpired")

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

if __name__=="__main__":
    call_particle_function()
