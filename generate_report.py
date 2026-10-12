import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List

import feedparser
import pytz
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel

LOCAL_TIMEZONE = "America/Vancouver"
REPORT_FILE = Path(__file__).with_name("latest_briefing.json")

WATCHLIST = {
    "Competitors": [
        "Solestial", "Ascent Solar Technologies", "mPower Technology",
        "PowerFilm Solar", "Swift Solar", "Arinna", "Merlin Solar",
        "MicroLink Devices", "Tandem PV", "Source Energy Company",
        "Spectrolab", "SolAero", "MiaSolé", "Flexell Space", "Active Surfaces",
    ],
    "Customers & Prospects": [
        "K2 Space", "spaceX", "NLR", "Texas A&M", "Caltech",
        "Jet Propulsion Laboratory", "JPL", "Glenn Research Center",
        "NASA Ames Research Center", "Opterus R&D", "National Renewable Energy Laboratory",
        "NREL", "MMA Space", "Starpath", "Deployable Space Systems", "Redwire",
        "Star Catcher Industries", "University Nanosatellite Program", "CubeSat Launch Initiative",
    ],
    "Material Suppliers & Partners": [
        "NeXolve", "Applied Aerospace", "Sheldahl", "DUNMORE", "Fralock",
        "Flexible Circuit Technologies", "Axiom Materials", "Hexcel Corporation",
        "Kaneka Aerospace", "Toray Group",
    ],
    "Materials & Products": [
        "polyimide film", "colorless polyimide", "CPI", "bifacial solar cell",
        "heterojunction solar cell", "space-grade adhesive", "solar blanket",
        "flexible solar array", "flexible solar panel", "bifacial solar", "CIGS",
        "perovskite", "GaAs", "CP1", "multijunction", "thin-film", "DragonSCALES", "ROSA",
    ],
}

FEEDS = [
    "https://spacenews.com/feed/",
    "https://www.nasaspaceflight.com/feed/",
    "https://www.space.com/feeds.xml",
    "https://spaceq.ca/feed/",
    "https://payloadspace.com/feed/",
    "https://europeanspaceflight.com/feed/",
    "https://www.nasa.gov/feed/",
    "https://www.solarpowerworldonline.com/feed/",
    "https://pv-magazine-usa.com/feed/",
    "https://www.pv-tech.org/feed/",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://spectrum.ieee.org/rss/aerospace",
]


class NewsItem(BaseModel):
    title: str
    summary: str
    key_points: List[str]
    connection_ideas: List[str]
    link: str
    relevance_rating: int
    relevance_reason: str


class Section(BaseModel):
    section_title: str
    items: List[NewsItem]


class DailyBriefing(BaseModel):
    sections: List[Section]
    top_priorities: List[NewsItem]


SYSTEM_INSTRUCTION = (
    "You are the market intelligence analyst assisting Paul Zhu, International Project "
    "Director at Heliofold, an aerospace materials and space solar technology enterprise. "
    "Heliofold sources from a manufacturing base in China and supplies North American satellite "
    "builders, university labs, and research programs with: Bifacia,a high-performance colorless polyimide"
    "film engineered as a direct drop-in replacement for traditional amber PI substrates. It matches mechanical"
    " strength and environmental resistance while enabling bifacial power gain and cooler solar-cell operation. "
    "Heliofold also actively tracks the orbital degradation and commercial viability of space-based "
    "perovskite solar cells. Heliofold's long-term goal is a double-sided, transparent, flexible "
    "solar blanket that fuses these product lines into one laminate.\n\n"
    "Heliofold's current and target customers include organizations like K2 Space, NLR, "
    "Texas A&M, and Caltech, and its broader market includes satellite manufacturers, "
    "constellation operators, university satellite programs, and space agencies. A known "
    "competitor is Solestial.\n\n"
    "I will give you a list of today's aerospace, solar, and AI news. Read all of it and "
    "organize it into a Daily Briefing using the required JSON schema. Rules:\n"
    "1. Group items into sections such as Satellite & Spacecraft, Solar & Materials, "
    "AI & Autonomy, Industry & Funding — only include sections that have items.\n"
    "2. Each item's summary should be 2-3 plain-text sentences, no markdown formatting.\n"
    "3. key_points: extract 3-5 short, concrete facts from the article as separate short "
    "phrases (not full sentences with the summary repeated) — numbers, names, dates, "
    "outcomes. These should let someone skim the gist without reading the summary.\n"
    "4. connection_ideas: give exactly 5 distinct, concrete ways this article could connect "
    "to Heliofold. Vary the angle across the 5 — for example one about a product line fit "
    ", one about production, logistics, or US-China supply "
    "chain, one about a potential customer or partnership, one about competitive positioning, "
    "and one about R&D direction. Each should be a single specific sentence, "
    "not generic ('this could be relevant to our market').\n"
    "5. Rate every item's relevance to Heliofold from 1 to 5: "
    "5 = directly actionable (a named potential customer, competitor, or supply chain event), "
    "4 = strong strategic relevance (market trend directly touching Heliofold's product lines), "
    "3 = moderately relevant (general space/solar industry movement worth awareness), "
    "2 = tangential (adjacent field, limited direct impact), "
    "1 = background noise (interesting but not actionable for Heliofold).\n"
    "6. Give a one-sentence reason for each rating.\n"
    "7. Always include the original URL exactly as provided.\n"
    "8. Keep each item's title EXACTLY as given in the source text (do not reword or "
    "shorten it) so it can be matched back to the original article.\n"
    "9. Some articles will include a line like '[WATCHLIST MATCH: Competitors - Solestial]' "
    "— this means the article mentions a term Heliofold specifically tracks (a named "
    "competitor, customer/prospect, or core material/product). Treat any watchlist match as "
    "a strong signal and rate it 4 or 5 unless the mention is clearly trivial or unrelated "
    "to Heliofold's business despite the keyword appearing.\n"
    "10. In top_priorities, list only the 3 highest-rated items across the whole briefing, "
    "in descending order of rating."
)


def find_watchlist_matches(text: str):
    lowered = text.lower()
    return [
        (category, term)
        for category, terms in WATCHLIST.items()
        for term in terms
        if term.lower() in lowered
    ]


def compile_news():
    compiled_news = []
    watchlist_by_title = {}

    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            logging.exception("Unable to fetch feed %s", feed_url)
            continue

        if feed.bozo and not feed.entries:
            logging.warning("Unable to read feed %s: %s", feed_url, feed.bozo_exception)
            continue

        for entry in feed.entries[:4]:
            title = entry.get("title", "No Title")
            link = entry.get("link", "")
            summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(
                separator=" ", strip=True
            )
            matches = find_watchlist_matches(f"{title} {summary}")
            if matches:
                watchlist_by_title[title] = matches

            article = f"Title: {title}\nSummary: {summary}\nLink: {link}\n"
            if matches:
                match_text = ", ".join(f"{category} - {term}" for category, term in matches)
                article += f"[WATCHLIST MATCH: {match_text}]\n"
            compiled_news.append(article)

    if not compiled_news:
        raise RuntimeError("No news articles could be loaded from any configured feed.")

    return "\n".join(compiled_news), watchlist_by_title


def generate_daily_report(client, all_news_text: str) -> DailyBriefing:
    prompt = f"Here is today's news:\n\n{all_news_text}\n\nPlease build the Daily Briefing."
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=DailyBriefing,
                ),
            )
            if getattr(response, "parsed", None) is not None:
                return response.parsed
            return DailyBriefing(**json.loads(response.text))
        except Exception as error:
            if "503" in str(error) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def save_report(data):
    temp_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=REPORT_FILE.parent,
            prefix=".latest_briefing.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(data, temp_file)
        os.replace(temp_path, REPORT_FILE)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    news, watchlist_by_title = compile_news()
    client = genai.Client(api_key=api_key)
    briefing = generate_daily_report(client, news)
    now = datetime.now(pytz.timezone(LOCAL_TIMEZONE))
    data = {
        "date": now.strftime("%Y-%m-%d"),
        "timestamp": now.strftime("%I:%M %p"),
        "briefing": briefing.model_dump(),
        "watchlist_by_title": watchlist_by_title,
    }
    save_report(data)
    logging.info("Saved daily report to %s.", REPORT_FILE)


if __name__ == "__main__":
    main()
