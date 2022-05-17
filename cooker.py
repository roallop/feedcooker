import datetime
import random
import urllib.parse
import dateutil.parser
from typing import Type, List

import feedparser
import requests
from jsonfeed import JSONFeed
from feedgenerator import Atom1Feed, SyndicationFeed

from filter import Filter
from util import logger, try_load_resp, save_resp


class Cooker(object):
    def __init__(
        self,
        name: str,
        repository_owner: str,
        repository: str,
        recipe: dict,
        limit: int,
    ):
        self.title = f"{name}"
        self.description = recipe.get("description")
        if not self.description:
            self.description = "Auto generated by feedcooker with love."
        self.home_page_url = f"https://github.com/{repository}"
        self.feed_url = f"https://raw.githubusercontent.com/{repository}/deploy/well-done/{urllib.parse.quote(name)}.json"
        self.author_name = repository_owner
        self.author_link = f"https://github.com/{repository_owner}"

        self.feeds_urls = recipe["urls"]
        # fetch in different order
        random.shuffle(self.feeds_urls)
        self.limit = limit

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "feedcooker 0.1"})
        self.filters = Filter.from_dicts(recipe.get("filters"))

    def cook(self) -> (JSONFeed, Atom1Feed):
        feed_items = []
        for url in self.feeds_urls:
            logger.debug(f"Fetching {url}")

            try:
                items = self._fetch_feed_items(url)
                count1 = len(items)
                items = self._filter_items(url, items)
                count2 = len(items)
                feed_items.extend(items)
            except Exception as e:
                logger.error(f"Failed to fetch {url}: {e}")
                continue
            logger.info(f"{url} {count1}/{count2} items")

        feed_items.sort(key=lambda x: x["pubdate"], reverse=True)

        logger.info(f"Final items {len(feed_items)}")

        return self._generate_feed(JSONFeed, feed_items), self._generate_feed(
            Atom1Feed, feed_items
        )

    def _fetch_url(self, url: str):
        headers = {}
        if last_resp := try_load_resp(url):
            headers["If-None-Match"] = last_resp.headers.get("ETag")
            headers["If-Modified-Since"] = last_resp.headers.get("Last-Modified")

        resp = self.session.get(url, timeout=5, headers=headers)
        if not resp.ok and last_resp:
            logger.warn(f"{url} failed, using cached response")
            return last_resp
        resp.raise_for_status()

        if resp.status_code == 304 and last_resp:
            logger.info(f"{url} Not modified")
            return last_resp

        return resp

    # fetch feed from url
    def _fetch_feed_items(self, url: str) -> List[dict]:
        resp = self._fetch_url(url)

        content_type = resp.headers["Content-Type"]
        logger.debug(f"content type: {content_type}, encoding: {resp.encoding}")
        if resp.encoding is None:
            resp.encoding = "utf-8"

        if content_type.startswith("application/json") or url.endswith(".json"):
            feed = resp.json()
            results = [
                self._json_feed_to_feed_item(feed, item) for item in feed["items"]
            ]
            save_resp(resp)
            return results

        f = feedparser.parse(resp.text)
        if f is None or f["bozo"]:
            ex = f.get("bozo_exception") if f else "Unknown error"
            raise Exception(f"Failed to parse feed: {ex}")

        results = [self._entry_to_feed_item(f.feed, e) for e in f.entries]
        save_resp(resp)
        return results

    @staticmethod
    def _json_feed_to_feed_item(feed: dict, e: dict) -> dict:
        item = {
            "title": e["title"],
            "link": e["url"],
            "unique_id": e["id"],
        }

        summary = e.get("summary")
        content = e.get("content_html") if e.get("content_html") else e.get("content")

        if content:
            # prefer use content as description
            item["description"] = content
            item["content"] = content
        elif summary:
            item["description"] = summary
        else:
            item["description"] = ""

        author_detail = e.get("author") if e.get("author") else feed.get("author")
        if author_detail:
            item["author_name"] = author_detail.get("name")
            item["author_link"] = author_detail.get("url")

        pubdate = (
            e.get("date_published")
            if e.get("date_published")
            else e.get("date_modified")
        )
        if pubdate:
            item["pubdate"] = dateutil.parser.parse(pubdate)
        else:
            item["pubdate"] = datetime.datetime.now()

        update = e.get("date_modified")
        if update:
            item["update"] = dateutil.parser.parse(update)

        logger.debug(f"item: {item}")
        return item

    # mapping rss/atom entry to JSONFeed item(using in JSONFeed.add_item)
    @staticmethod
    def _entry_to_feed_item(feed, e) -> dict:
        item = {
            "title": e["title"],
            "link": e["link"],
            "unique_id": e["id"],
        }

        summary = e.get("summary")
        content = e.get("content")
        if content and len(content) > 0:
            content = content[0].get("value")

        if content:
            # prefer use content as description
            item["description"] = content
            item["content"] = content
        elif summary:
            item["description"] = summary
        else:
            item["description"] = ""

        author_detail = (
            e.get("author_detail")
            if e.get("author_detail")
            else feed.get("author_detail")
        )
        if author_detail:
            item["author_name"] = author_detail.get("name")
            item["author_email"] = author_detail.get("email")
            item["author_link"] = author_detail.get("href")
        elif e.get("author"):
            item["author_name"] = e.get("author")
        elif feed.get("author"):
            item["author_name"] = feed.get("author")

        if item.get("author_name") is None:
            item["author_name"] = feed.get("title", e["link"].split("/")[2])
        else:
            item[
                "author_name"
            ] = f'{item["author_name"]} from {feed.get("title", e["link"].split("/")[2])}'

        update = e.get("updated_parsed")
        if update:
            item["update"] = datetime.datetime(*update[:6])

        pubdate = e.get("published_parsed") if e.get("published_parsed") else update
        if pubdate:
            item["pubdate"] = datetime.datetime(*pubdate[:6])
        else:
            item["pubdate"] = datetime.datetime.now()

        logger.debug(f"item: {item}")
        return item

    def _generate_feed(
        self, gen_cls: Type[SyndicationFeed], items: List[dict]
    ) -> SyndicationFeed:
        feed = gen_cls(
            title=self.title,
            link=self.home_page_url,
            description=self.description,
            feed_url=self.feed_url,
            author_name=self.author_name,
            author_link=self.author_link,
        )
        for i in items:
            feed.add_item(**i)
        return feed

    def _filter_items(self, url: str, items):
        if len(items) == 0:
            return items

        for f in self.filters:
            count = len(items)
            items = f.filter_items(items)
            if count != len(items):
                logger.debug(f"-{count - len(items)} by {f.__class__.__name__} {url}")

        return items[: self.limit]
