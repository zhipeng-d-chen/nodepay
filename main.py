import asyncio
import aiohttp
import time
import uuid
from loguru import logger
from colorama import Fore, Style, init
import sys
import logging
logging.disable(logging.ERROR)
from utils.banner import banner

init(autoreset=True)

logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>", colorize=True)
logger.level("INFO", color=f"{Fore.GREEN}")
logger.level("DEBUG", color=f"{Fore.CYAN}")
logger.level("WARNING", color=f"{Fore.YELLOW}")
logger.level("ERROR", color=f"{Fore.RED}")
logger.level("CRITICAL", color=f"{Style.BRIGHT}{Fore.RED}")


def show_copyright():
    print(Fore.MAGENTA + Style.BRIGHT + banner + Style.RESET_ALL)
    confirm = input("Press Enter to continue or Ctrl+C to exit... ")
    if confirm.strip() == "":
        print("Continuing with the program...")
    else:
        print("Exiting the program.")
        exit()

PING_INTERVAL = 180
RETRIES = 120
TOKEN_FILE = 'np_tokens.txt'

DOMAIN_API = {
    "SESSION": "https://api.nodepay.org/api/auth/session",
    "PING": "https://nw.nodepay.org/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
browser_id = None
account_info = {}
last_ping_time = {}

def uuidv4():
    return str(uuid.uuid4())

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("Invalid response")
    return resp

proxy_auth_status = {}  

async def render_profile_info(proxy, token):
    global browser_id, account_info

    try:
        if not proxy_auth_status.get(proxy):  
            browser_id = uuidv4()
            response = await call_api(DOMAIN_API["SESSION"], {}, proxy, token)
            if response is None:
                logger.info(f"{Fore.YELLOW}Skipping proxy {proxy} due to 403 error.")
                return
            valid_resp(response)
            account_info = response["data"]
            if account_info.get("uid"):
                proxy_auth_status[proxy] = True  
                save_session_info(proxy, account_info)
            else:
                handle_logout(proxy)
                return
        
        await start_ping(proxy, token)

    except Exception as e:
        logger.error(f"{Fore.RED}Error in render_profile_info for proxy {proxy}: {e}")

async def call_api(url, data, proxy, token, max_retries=3):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://app.nodepay.ai",
    }

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True)) as session:
        for attempt in range(max_retries):
            try:
                async with session.post(url, json=data, headers=headers, proxy=proxy, timeout=10) as response:
                    response.raise_for_status()
                    resp_json = await response.json()
                    return valid_resp(resp_json)

            except aiohttp.ClientResponseError as e:
                logger.error(f"{Fore.RED}API call error on attempt {attempt + 1} for proxy {proxy}: {e}")
                if e.status == 403:
                    logger.warning(f"{Fore.YELLOW}403 Forbidden encountered on attempt {attempt + 1}: {e}")
                    return None
            except aiohttp.ClientConnectionError as e:
                logger.error(f"{Fore.RED}Connection error on attempt {attempt + 1} for proxy {proxy}: {e}")
            except aiohttp.Timeout as e:
                logger.warning(f"{Fore.YELLOW}Timeout on attempt {attempt + 1} for proxy {proxy}: {e}")
            except Exception as e:
                logger.critical(f"{Style.BRIGHT}{Fore.RED}Unexpected error on attempt {attempt + 1} for proxy {proxy}: {e}")

            await asyncio.sleep(2 ** attempt)

    logger.error(f"{Fore.RED}Failed API call to {url} after {max_retries} attempts with proxy {proxy}")
    return None

async def start_ping(proxy, token):
    try:
        while True:
            await ping(proxy, token)
            await asyncio.sleep(PING_INTERVAL)
    except asyncio.CancelledError:
        logger.info(f"{Fore.YELLOW}Ping task for proxy {proxy} was cancelled")
    except Exception as e:
        logger.error(f"{Fore.RED}Error in start_ping for proxy {proxy}: {e}")

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
            "timestamp": int(time.time())
        }

        response = await call_api(DOMAIN_API["PING"], data, proxy, token)
        if response["code"] == 0:
            logger.info(f"{Fore.GREEN}Ping successful via proxy {proxy}: {response}")
            RETRIES = 0
            status_connect = CONNECTION_STATES["CONNECTED"]
        else:
            handle_ping_fail(proxy, response)
    except Exception as e:
        logger.error(f"{Fore.RED}Ping failed via proxy {proxy}: {e}")
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
    logger.info(f"{Fore.YELLOW}Logged out and cleared session info for proxy {proxy}")

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

def save_session_info(proxy, data):
    data_to_save = {
        "uid": data.get("uid"),
        "browser_id": browser_id
    }
    pass

def load_session_info(proxy):
    return {}

def load_tokens_from_file(filename):
    try:
        with open(filename, 'r') as file:
            tokens = file.read().splitlines()
        return tokens
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        raise SystemExit("Exiting due to failure in loading tokens")

async def send_data_to_server(url, data, token):
    proxy = None  
    response = await call_api(url, data, proxy, token)

    if response is not None:
        logger.info(f"Response received: {response}")
    else:
        logger.error("Failed to receive response.")
        
async def main():
    show_copyright()
    print("Welcome to the main program!")

    url = "https://api.nodepay.org/api/auth/session"
    data = {
        "cache-control": "no-cache, no-store, max-age=0, must-revalidate",
        "cf-cache-status": "DYNAMIC",
    }

    all_proxies = load_proxies('proxy.txt')
    tokens = load_tokens_from_file(TOKEN_FILE)

    for token in tokens:
        await send_data_to_server(url, data, token)
        await asyncio.sleep(10)

    while True:
        for token in tokens:
            tasks = {asyncio.create_task(render_profile_info(proxy, token)): proxy for proxy in all_proxies}

            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                logger.info(f"{Fore.YELLOW}Completed task for proxy: {tasks[task]}")
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

