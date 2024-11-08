import asyncio
import aiohttp
import time
import uuid
import json
from loguru import logger
from colorama import Fore, Style, init
import sys
import os
from utils.banner import banner

# Initialize colorama and configure loguru
init(autoreset=True)
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>", colorize=True)

PING_INTERVAL = 180
RETRIES = 120
TOKEN_FILE = 'np_tokens.txt'
SESSION_FILE = 'sessions.json'
DOMAIN_API = {
    "SESSION": "https://api.nodepay.org/api/auth/session?",
    "PING": "https://nw.nodepay.org/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
proxy_auth_status = {}
browser_id = None
account_info = {}
last_ping_time = {}

def uuidv4():
    return str(uuid.uuid4())

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("Invalid response")
    return resp

# Save session information to JSON file
def save_session_info(proxy, data):
    session_data = load_all_sessions()
    session_data[proxy] = {
        "uid": data.get("uid"),
        "browser_id": browser_id
    }
    with open(SESSION_FILE, 'w') as file:
        json.dump(session_data, file)
    logger.info(f"Session saved for proxy {proxy}")

# Load all sessions from JSON file
def load_all_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as file:
            return json.load(file)
    return {}

# Load a specific session for a given proxy
def load_session_info(proxy):
    session_data = load_all_sessions()
    return session_data.get(proxy, {})

async def render_profile_info(proxy, token):
    global browser_id, account_info

    try:
        if not proxy_auth_status.get(proxy):
            
            saved_session = load_session_info(proxy)
            if saved_session:
                browser_id = saved_session["browser_id"]
                account_info["uid"] = saved_session["uid"]
                proxy_auth_status[proxy] = True
                logger.info(f"Loaded saved session for proxy {proxy}")
            else:
                browser_id = uuidv4()
                response = await call_api(DOMAIN_API["SESSION"], {}, proxy, token)
                if response:
                    valid_resp(response)
                    account_info = response["data"]
                    if account_info.get("uid"):
                        proxy_auth_status[proxy] = True
                        save_session_info(proxy, account_info)
                        logger.info(f"Proxy {proxy} authenticated successfully.")
                    else:
                        handle_logout(proxy)
                        
                else:
                    return

        await start_ping(proxy, token)

    except Exception as e:
        logger.error(f"Exception in render_profile_info for proxy {proxy}: {e}")

async def call_api(url, data, proxy, token, max_retries=3):
    headers = {
        "Authorization": f"Bearer {token}",
        'accept': '*/*',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0',
    }

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True)) as session:
        
        try:
            async with session.options(url, headers=headers, proxy=proxy, timeout=10) as options_response:
                if options_response.status not in (200, 204):
                    return None
        except Exception as e:
            return None

        # Send the POST request if OPTIONS was successful
        for attempt in range(max_retries):
            try:
                async with session.post(url, json=data, headers=headers, proxy=proxy, timeout=10) as response:
                    response.raise_for_status()
                    resp_json = await response.json()
                    return valid_resp(resp_json)
            except aiohttp.ClientResponseError as e:
                if e.status == 403:
                    logger.warning(f"API call to {url} failed with status 403 on proxy {proxy}")
                    return None
            except aiohttp.ClientConnectionError as e:
                logger.warning(f"Connection error on attempt {attempt + 1} for proxy {proxy}: {e}")
            except Exception as e:
                logger.error(f"Exception during API call attempt {attempt + 1} for proxy {proxy}: {e}")
            await asyncio.sleep(2 ** attempt)

    logger.error(f"Failed API call to {url} after {max_retries} attempts with proxy {proxy}")
    return None


async def start_ping(proxy, token):
    try:
        while True:
            await ping(proxy, token)
            await asyncio.sleep(PING_INTERVAL)
    except asyncio.CancelledError:
        logger.info(f"Ping task for proxy {proxy} was cancelled")
    except Exception as e:
        logger.error(f"Error in start_ping for proxy {proxy}: {e}")

async def ping(proxy, token):
    global last_ping_time, RETRIES, status_connect

    current_time = time.time()
    if proxy in last_ping_time and (current_time - last_ping_time[proxy]) < PING_INTERVAL:
        return

    last_ping_time[proxy] = current_time

    try:
        data = {
            "id": account_info.get("uid"),
            "browser_id": browser_id,
            "timestamp": int(time.time()),
            "version": '2.2.7'
        }
        response = await call_api(DOMAIN_API["PING"], data, proxy, token)
        if response and response["code"] == 0:
            logger.info(f"Ping successful via proxy {proxy}")
            RETRIES = 0
            status_connect = CONNECTION_STATES["CONNECTED"]
        else:
            handle_ping_fail(proxy, response)
    except Exception as e:
        logger.error(f"Ping error for proxy {proxy}: {e}")
        handle_ping_fail(proxy, None)

def handle_ping_fail(proxy, response):
    global RETRIES, status_connect
    RETRIES += 1
    if response and response.get("code") == 403:
        handle_logout(proxy)
    elif RETRIES < 2:
        status_connect = CONNECTION_STATES["DISCONNECTED"]
    else:
        status_connect = CONNECTION_STATES["DISCONNECTED"]
        

def handle_logout(proxy):
    global status_connect, account_info
    status_connect = CONNECTION_STATES["NONE_CONNECTION"]
    account_info = {}
    save_status(proxy, None)
    logger.info(f"Logged out and cleared session info for proxy {proxy}")

def load_proxies(proxy_file):
    try:
        with open(proxy_file, 'r') as file:
            proxies = file.read().splitlines()
        return proxies
    except Exception as e:
        logger.error(f"Failed to load proxies: {e}")
        raise SystemExit("Exiting due to failure in loading proxies")

def save_status(proxy, status):
    pass

def load_tokens_from_file(filename):
    try:
        with open(filename, 'r') as file:
            tokens = file.read().splitlines()
        return tokens
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        raise SystemExit("Exiting due to failure in loading tokens")
        
        
async def main():
    print(Fore.MAGENTA + Style.BRIGHT + banner + Style.RESET_ALL)
    logger.info("Starting program execution")
    await asyncio.sleep(5)
    
    all_proxies = load_proxies('proxy.txt')
    tokens = load_tokens_from_file(TOKEN_FILE)

    
    while True:
        for token in tokens:
            tasks = {asyncio.create_task(render_profile_info(proxy, token)): proxy for proxy in all_proxies}
            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                tasks.pop(task)

            for proxy in set(all_proxies) - set(tasks.values()):
                new_task = asyncio.create_task(render_profile_info(proxy, token))
                tasks[new_task] = proxy

            await asyncio.sleep(3)
        await asyncio.sleep(10)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Program terminated by user.")
