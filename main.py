import hashlib
import json
import os
import atexit
import time
from datetime import datetime
from typing import List

import feedparser
import pytz
import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from fpdf import FPDF
from google import genai
from google.genai import types
from pydantic import BaseModel

# Pull the API key from Streamlit's secure secrets manager
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# ---------------------------------------------------------------------------
# Configuration & Storage
# ---------------------------------------------------------------------------
REPORT_FILE = "latest_briefing.json"
LOCAL_TIMEZONE = "America/Vancouver"

# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
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
        "cover glass", "polyimide film", "colorless polyimide", "HJT solar cell",
        "heterojunction solar cell", "space-grade adhesive", "solar blanket",
        "flexible solar array", "flexible solar panel", "bifacial solar", "CIGS",
        "perovskite", "GaAs", "CP1", "multijunction", "thin-film", "DragonSCALES", "ROSA",
    ],
}

def find_watchlist_matches(text: str):
    if not text:
        return []
    lowered = text.lower()
    matches = []
    for category, terms in WATCHLIST.items():
        for term in terms:
            if term.lower() in lowered:
                matches.append((category, term))
    return matches

# ---------------------------------------------------------------------------
# Structured Output Schemas
# ---------------------------------------------------------------------------
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
    "builders, university labs, and research programs with: Ce-UTG cover glass (radiation-hardened "
    "cell protection), SCPI colorless polyimide film (flexible transparent substrates), "
    "polyamic acid (PAA) resins, P-type HJT solar cells, and space-grade silicone adhesives. "
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
    "(cover glass / polyimide film / PAA / HJT / perovskite), one about production, logistics, or US-China supply "
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

RATING_LABEL = {5: "Critical", 4: "High", 3: "Moderate", 2: "Low", 1: "Background"}
RATING_ACCENT = {5: "#8a1f2d", 4: "#b9862f", 3: "#5c6b73", 2: "#8a8a8a", 1: "#bcbcbc"}
BRAND_NAVY = "#0b1f3a"
BRAND_GOLD = "#c9a227"

def clean_html(raw_html):
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)

def fetch_feed_entries(feed_url, limit=4):
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            return []
        return feed.entries[:limit]
    except Exception:
        return []

def generate_daily_report(all_news_text) -> DailyBriefing:
    prompt = f"Here is today's news:\n\n{all_news_text}\n\nPlease build the Daily Briefing."
    
    # Retry mechanism for 503 High Demand errors
    max_retries = 3
    for attempt in range(max_retries):
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
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise e

def generate_social_post(item: NewsItem, connection_idea: str, platform: str) -> str:
    if platform == "LinkedIn":
        style_notes = (
            "LinkedIn Guidelines (Maximum 200 words):\n"
            "1. Hook: Start with a strong, attention-grabbing opening about this specific development. Do not use generic openings like 'Exciting news in the space industry.'\n"
            "2. Body: Briefly explain the development and why it matters to the industry. Do not just summarize the article; add context. Make it understandable to a professional audience without excessive technical jargon.\n"
            "3. Ending: Provide a meaningful takeaway or forward-looking thought. Whenever naturally relevant, connect the development to Heliofold US (space technology, advanced materials, solar cells, lightweight power systems, or space infrastructure). The connection must feel natural and meaningful, not like an advertisement. If the news is genuinely unrelated, do not force a connection; end with a relevant industry takeaway instead.\n\n"
            "Tone: Professional but human, written from the perspective of Paul Zhu, International Project Director at Heliofold. Avoid excessive emojis and generic corporate language. Never make unsupported claims about Heliofold. Max 2 hashtags at the end. Put the source link on its own line at the end."
        )
    else:
        style_notes = (
            "X (Twitter) tone: punchy, technical, under 280 characters total including the link. "
            "No fluff, one clear point. Max 2 hashtags."
        )

    prompt = (
        f"Write a {platform} post about this news article, "
        f"built specifically around this angle: \"{connection_idea}\"\n\n"
        f"Article title: {item.title}\n"
        f"Article summary: {item.summary}\n"
        f"Source link: {item.link}\n\n"
        f"{style_notes}\n"
        "Output only the post text, nothing else."
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.6),
            )
            return response.text.strip()
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise e

def item_key(item: NewsItem) -> str:
    return hashlib.md5(item.link.encode("utf-8")).hexdigest()[:10]

# ---------------------------------------------------------------------------
# Background Task & Storage Handlers
# ---------------------------------------------------------------------------
def execute_report_generation():
    compiled_news = ""
    watchlist_by_title = {}

    for feed_url in FEEDS:
        entries = fetch_feed_entries(feed_url)
        for entry in entries:
            title = entry.get("title", "No Title")
            link = entry.get("link", "")
            summary_html = entry.get("summary", "")
            clean_summary = clean_html(summary_html)

            matches = find_watchlist_matches(f"{title} {clean_summary}")
            if matches:
                watchlist_by_title[title] = matches

            compiled_news += f"Title: {title}\nSummary: {clean_summary}\nLink: {link}\n"
            if matches:
                match_str = ", ".join(f"{cat} - {term}" for cat, term in matches)
                compiled_news += f"[WATCHLIST MATCH: {match_str}]\n"
            compiled_news += "\n"

    try:
        briefing = generate_daily_report(compiled_news)
        tz = pytz.timezone(LOCAL_TIMEZONE)
        data = {
            "date": datetime.now(tz).strftime("%Y-%m-%d"),
            "timestamp": datetime.now(tz).strftime("%I:%M %p"),
            "briefing": briefing.model_dump() if hasattr(briefing, 'model_dump') else briefing.dict(),
            "watchlist_by_title": watchlist_by_title
        }
        with open(REPORT_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Failed to generate automated report: {e}")

@st.cache_resource
def start_scheduler():
    tz = pytz.timezone(LOCAL_TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(execute_report_generation, 'cron', hour=8, minute=0)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler

def load_latest_report():
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r") as f:
            return json.load(f)
    return None

# ---------------------------------------------------------------------------
# Styling & Rendering
# ---------------------------------------------------------------------------
def inject_style():
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}

html, body, [class*="css"] {{
    font-family: 'IBM Plex Sans', sans-serif;
}}

.block-container {{
    padding-top: 1.5rem;
    max-width: 900px;
}}

.hf-masthead {{
    border-bottom: 3px solid {BRAND_GOLD};
    padding-bottom: 10px;
    margin-bottom: 6px;
}}
.hf-masthead h1 {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 700;
    color: {BRAND_NAVY};
    margin-bottom: 0;
    letter-spacing: -0.5px;
}}
.hf-masthead p {{
    color: #6b6b6b;
    font-size: 0.9em;
    margin-top: 2px;
    font-family: 'IBM Plex Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

.hf-card {{
    border: 1px solid #2a2a2a22;
    border-left: 4px solid var(--accent, #999);
    border-radius: 4px;
    padding: 14px 18px;
    margin-bottom: 16px;
    background: rgba(255,255,255,0.02);
}}
.hf-card h4 {{
    margin: 0 0 6px 0;
    font-size: 1.05em;
    font-weight: 600;
}}
.hf-rating-tag {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--accent, #999);
    border: 1px solid var(--accent, #999);
    border-radius: 3px;
    padding: 1px 7px;
    white-space: nowrap;
}}
.hf-watchlist-tag {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75em;
    color: {BRAND_GOLD};
    border: 1px solid {BRAND_GOLD};
    border-radius: 3px;
    padding: 1px 7px;
    white-space: nowrap;
}}
.hf-keypoints {{
    margin: 8px 0 10px 0;
    padding-left: 18px;
    font-size: 0.92em;
}}
.hf-keypoints li {{
    margin-bottom: 2px;
}}
.hf-reason {{
    font-size: 0.85em;
    color: #999;
    margin: 4px 0 2px 0;
}}
.hf-section-label {{
    font-family: 'IBM Plex Mono', monospace;
    text-transform: uppercase;
    font-size: 0.85em;
    letter-spacing: 1px;
    color: {BRAND_NAVY};
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-top: 28px;
    margin-bottom: 10px;
}}
</style>
""",
        unsafe_allow_html=True,
    )

def render_masthead():
    st.markdown(
        f"""
<div class="hf-masthead">
  <h1>Heliofold Daily Briefing</h1>
  <p>Space materials &amp; market intelligence — internal use</p>
</div>
""",
        unsafe_allow_html=True,
    )

def render_item(item: NewsItem, watchlist_by_title: dict, context: str = ""):
    accent = RATING_ACCENT.get(item.relevance_rating, "#999")
    label = RATING_LABEL.get(item.relevance_rating, "")
    matches = (watchlist_by_title or {}).get(item.title, [])

    key = f"{context}_{item_key(item)}"

    st.markdown(f'<div class="hf-card" style="--accent:{accent};">', unsafe_allow_html=True)

    top_l, top_r = st.columns([4, 2])
    with top_l:
        st.markdown(f"<h4>{item.title}</h4>", unsafe_allow_html=True)
    with top_r:
        badges = f'<span class="hf-rating-tag">{label} · {item.relevance_rating}/5</span>'
        if matches:
            match_labels = ", ".join(term for _cat, term in matches)
            badges = f'<span class="hf-watchlist-tag">Watchlist: {match_labels}</span> ' + badges
        st.markdown(f'<div style="text-align:right;">{badges}</div>', unsafe_allow_html=True)

    st.markdown(f"<p>{item.summary}</p>", unsafe_allow_html=True)

    if item.key_points:
        points_html = "".join(f"<li>{p}</li>" for p in item.key_points)
        st.markdown(f'<ul class="hf-keypoints">{points_html}</ul>', unsafe_allow_html=True)

    st.markdown(f'<p class="hf-reason">Why it matters: {item.relevance_reason}</p>', unsafe_allow_html=True)
    st.markdown(f'<a href="{item.link}" target="_blank" style="font-size:0.85em;">Read source →</a>', unsafe_allow_html=True)

    if item.connection_ideas:
        with st.expander("5 ways this connects to Heliofold"):
            for idx, idea in enumerate(item.connection_ideas):
                st.markdown(f"<div style='font-size:0.9em; margin-bottom: 8px;'>{idx + 1}. {idea}</div>", unsafe_allow_html=True)
                
                btn_col1, btn_col2, _ = st.columns([2, 2, 6])
                linkedin_key = f"draft_li_{key}_{idx}"
                x_key = f"draft_x_{key}_{idx}"

                platform_to_generate = None
                with btn_col1:
                    if st.button("Generate LinkedIn Post", key=linkedin_key):
                        platform_to_generate = "LinkedIn"
                with btn_col2:
                    if st.button("Generate X Post", key=x_key):
                        platform_to_generate = "X"

                if platform_to_generate:
                    with st.spinner(f"Writing {platform_to_generate} post..."):
                        try:
                            post_text = generate_social_post(item, idea, platform_to_generate)
                            st.session_state.setdefault("generated_posts", {})[f"{key}_{idx}"] = {
                                "text": post_text,
                                "platform": platform_to_generate,
                            }
                        except Exception as e:
                            st.error(f"Error generating post: {e}")

                generated = st.session_state.get("generated_posts", {}).get(f"{key}_{idx}")
                if generated:
                    st.caption(f"{generated['platform']} draft:")
                    st.code(generated["text"], language=None)

    st.markdown("</div>", unsafe_allow_html=True)

def render_briefing(briefing: DailyBriefing, watchlist_by_title: dict):
    if briefing.top_priorities:
        st.markdown('<div class="hf-section-label">Top 3 Priorities Today</div>', unsafe_allow_html=True)
        for i, item in enumerate(briefing.top_priorities):
            render_item(item, watchlist_by_title, context=f"top{i}")

    for s_idx, section in enumerate(briefing.sections):
        if not section.items:
            continue
        st.markdown(f'<div class="hf-section-label">{section.section_title}</div>', unsafe_allow_html=True)
        for i, item in enumerate(section.items):
            render_item(item, watchlist_by_title, context=f"sec{s_idx}_{i}")

def briefing_to_plain_text(briefing: DailyBriefing) -> str:
    lines = []
    def add_item(item: NewsItem):
        lines.append(item.title)
        lines.append(item.summary)
        for p in item.key_points:
            lines.append(f"  - {p}")
        lines.append(f"Heliofold Relevance: {item.relevance_rating}/5 - {item.relevance_reason}")
        lines.append(item.link)
        lines.append("")

    if briefing.top_priorities:
        lines.append("TOP 3 PRIORITIES TODAY")
        lines.append("")
        for item in briefing.top_priorities:
            add_item(item)
        lines.append("")

    for section in briefing.sections:
        if not section.items:
            continue
        lines.append(section.section_title.upper())
        lines.append("")
        for item in section.items:
            add_item(item)
        lines.append("")

    return "\n".join(lines)

def create_pdf(report_text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    replacements = {
        "—": "-", "–": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "…": "...", "→": "->",
        "★": "*", "☆": "-",
    }
    for orig, repl in replacements.items():
        report_text = report_text.replace(orig, repl)

    encoded_text = report_text.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 10, txt=encoded_text)

    return pdf.output(dest="S").encode("latin-1")

def main():
    st.set_page_config(page_title="Heliofold Daily Briefing", page_icon="🛰️", layout="wide")
    inject_style()
    render_masthead()

    start_scheduler()

    st.write(
        "Automatically pulls today's space, solar, and AI news, rates each item for relevance to "
        "Heliofold, and lets you draft ready-to-post LinkedIn or X content directly from key topics."
    )
    
    tz = pytz.timezone(LOCAL_TIMEZONE)
    current_date_str = datetime.now(tz).strftime("%Y-%m-%d")
    report_data = load_latest_report()

    if report_data:
        report_date = report_data.get("date")
        report_time = report_data.get("timestamp")
        
        if report_date == current_date_str:
            st.success(f"Showing today's report (Automatically generated at {report_time})")
        else:
            st.info(f"ℹ️ Today's Space News report has not been generated yet. Showing the most recent available report (from {report_date}).")
        
        briefing = DailyBriefing(**report_data["briefing"])
        watchlist_by_title = report_data.get("watchlist_by_title", {})
        
        render_briefing(briefing, watchlist_by_title)
        
        plain_text = briefing_to_plain_text(briefing)
        pdf_bytes = create_pdf(plain_text)
        st.download_button(
            label="Download as PDF",
            data=pdf_bytes,
            file_name=f"Heliofold_Daily_Briefing_{report_date}.pdf",
            mime="application/pdf",
        )
    else:
        st.warning("No reports have been generated yet. Click below to generate the first report.")

    with st.expander("Admin Controls"):
        if st.button("Force Generate Report Now"):
            with st.spinner("Compiling feeds and generating report (this may take a moment)..."):
                try:
                    execute_report_generation()
                    st.success("Report generated successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error generating report: {e}")

if __name__ == "__main__":
    main()