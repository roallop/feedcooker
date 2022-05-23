import logging
import os
import pickle
from typing import Optional

import requests

logging.basicConfig(
    level=os.environ.get("LOGLEVEL", logging.INFO),
    format="%(asctime)s %(name)s - [%(levelname)s] > %(message)s",
)
logger = logging.getLogger("feedcooker")

cache_folder = "./downloads"


def url_to_valid_filename(url: str) -> str:
    return url.replace("/", "_").replace(":", "_").replace("?", "_").replace(" ", "_")


def try_load_resp(url: str) -> Optional[requests.Response]:
    key = url_to_valid_filename(url)
    try:
        with open(os.path.join(cache_folder, key), "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        return None


def save_resp(url: str, resp: requests.Response):
    os.makedirs(cache_folder, exist_ok=True)

    key = url_to_valid_filename(url)
    with open(os.path.join(cache_folder, key), "wb") as f:
        pickle.dump(resp, f)


def put_github_action_env(key: str, value: str):
    env_file = os.getenv('GITHUB_ENV')
    if env_file is None:
        raise Exception("GITHUB_ENV is not set")

    with open(env_file, "a") as f:
        f.write(f"{key}<<EOF\n{value}\nEOF\n")


def xml_escape(s: str) -> str:
    from xml.sax.saxutils import escape
    return escape(s, {"'": "&apos;", '"': "&quot;"})
