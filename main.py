
Heliofold news agent · PY
import hashlib
import json
from typing import List
 
import feedparser
import streamlit as st
from bs4 import BeautifulSoup
from fpdf import FPDF
from google import genai
from google.genai import types
from pydantic import BaseModel
 
# Pull the API key from Streamlit's secure secrets manager
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
 
# ---------------------------------------------------------------------------
# Watchlist
# Keyword matching is done in plain Python (not left to the AI alone) so it's
# reliable and consistent every run. Matches are (a) surfaced to Gemini as
# extra context per article so its rating reasoning improves, and (b) shown
# as a separate badge on the website regardless of what rating the AI gives.
# Edit these lists freely as you learn about new competitors/customers.
# ---------------------------------------------------------------------------
 
WATCHLIST = {
    "Competitors": [
        "Solestial",
        # add more competitors here, e.g. "Company Name",
    ],
    "Customers & Prospects": [
        "K2 Space",
        "NLR",
        "Texas A&M",
        "Caltech",
        # add more named prospects/customers here
    ],
    "Materials & Products": [
        "cover glass",
        "polyimide film",
        "colorless polyimide",
        "HJT solar cell",
        "heterojunction solar cell",
        "space-grade adhesive",
        "solar blanket",
        "flexible solar array",
        "flexible solar panel",
        "bifacial solar",
    ],
}
 
 
def find_watchlist_matches(text: str):
    """Case-insensitive scan of a block of text against every watchlist term.
    Returns a list of (category, term) tuples for every match found."""
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
# Structured output schema
# Using a schema (instead of free text) means the website can render clean
# sections/cards and the PDF is built from the same reliable data, instead of
# trying to parse formatting out of loose AI-generated text.
# ---------------------------------------------------------------------------
 
class NewsItem(BaseModel):
    title: str
    summary: str
    key_points: List[str]        # 3-5 short bullet-point facts pulled from the article
    connection_ideas: List[str]  # exactly 5 distinct ways this ties back to Heliofold
    link: str
    relevance_rating: int  # 1-5
    relevance_reason: str
 
 
class Section(BaseModel):
    section_title: str
    items: List[NewsItem]
 
 
class DailyBriefing(BaseModel):
    sections: List[Section]
    top_priorities: List[NewsItem]
 
 
system_instruction = (
    "You are the market intelligence analyst for Heliofold US, a space-grade materials "
    "company based in El Segundo, California. Heliofold sources from a manufacturing base "
    "in China and supplies North American satellite builders, university labs, and research "
    "programs with: Ce-UTG cover glass (radiation-hardened cell protection), SCPI colorless "
    "polyimide film (flexible transparent substrates), P-type HJT solar cells, and space-grade "
    "silicone adhesives (DPA-8800, GPA-8811). Heliofold's long-term goal is a double-sided, "
    "transparent, flexible solar blanket that fuses these product lines into one laminate.\n\n"
    "Heliofold's current and target customers include organizations like K2 Space, NLR, "
    "Texas A&M, and Caltech, and its broader market includes satellite manufacturers, "
    "constellation operators, university satellite programs, and space agencies. A known "
    "competitor is Solestial.\n\n"
    "I will give you a list of today's aerospace, solar, and AI news. Read all of it and "
    "organize it into a Daily Briefing using the required JSON schema. Rules:\n"
    "1. Group items into sections such as Satellite & Spacecraft, Solar & Materials, "
    "AI & Autonomy, Industry & Funding \u2014 only include sections that have items.\n"
    "2. Each item's summary should be 2-3 plain-text sentences, no markdown formatting.\n"
    "3. key_points: extract 3-5 short, concrete facts from the article as separate short "
    "phrases (not full sentences with the summary repeated) \u2014 numbers, names, dates, "
    "outcomes. These should let someone skim the gist without reading the summary.\n"
    "4. connection_ideas: give exactly 5 distinct, concrete ways this article could connect "
    "to Heliofold. Vary the angle across the 5 \u2014 for example one about a product line fit "
    "(cover glass / polyimide film / HJT cells / adhesives), one about production or supply "
    "chain, one about a potential customer or partnership, one about competitive positioning, "
    "and one about team/talent or R&D direction. Each should be a single specific sentence, "
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
    "\u2014 this means the article mentions a term Heliofold specifically tracks (a named "
    "competitor, customer/prospect, or core material/product). Treat any watchlist match as "
    "a strong signal and rate it 4 or 5 unless the mention is clearly trivial or unrelated "
    "to Heliofold's business despite the keyword appearing.\n"
    "10. In top_priorities, list only the 3 highest-rated items across the whole briefing, "
    "in descending order of rating."
)
 
FEEDS = [
    # Core space / satellite industry
    "https://spacenews.com/feed/",
    "https://www.nasaspaceflight.com/feed/",
    "https://www.space.com/feeds.xml",
    "https://spaceq.ca/feed/",
    "https://www.parabolicarc.com/feed/",
    "https://payloadspace.com/feed/",
    "https://europeanspaceflight.com/feed/",
 
    # NASA official
    "https://www.nasa.gov/feed/",
 
    # Solar / materials / manufacturing
    "https://www.solarpowerworldonline.com/feed/",
    "https://pv-magazine-usa.com/feed/",
    "https://www.pv-tech.org/feed/",
 
    # AI / tech
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://spectrum.ieee.org/rss/aerospace",
]
 
# Muted, editorial palette instead of bright "AI SaaS" pill colors \u2014
# used as a left-border accent rather than a loud badge fill.
RATING_LABEL = {
    5: "Critical",
    4: "High",
    3: "Moderate",
    2: "Low",
    1: "Background",
}
 
RATING_ACCENT = {
    5: "#8a1f2d",  # deep red
    4: "#b9862f",  # muted gold/amber
    3: "#5c6b73",  # slate
    2: "#8a8a8a",  # gray
    1: "#bcbcbc",  # light gray
}
 
BRAND_NAVY = "#0b1f3a"
BRAND_GOLD = "#c9a227"
 
 
def clean_html(raw_html):
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
 
 
def fetch_feed_entries(feed_url, limit=4):
    """Fetch entries from a single feed, returning an empty list on failure
    instead of crashing the whole run."""
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            st.warning(f"Could not read feed: {feed_url}")
            return []
        return feed.entries[:limit]
    except Exception as e:
        st.warning(f"Skipped {feed_url} due to error: {e}")
        return []
 
 
def generate_daily_report(all_news_text) -> DailyBriefing:
    prompt = f"Here is today's news:\n\n{all_news_text}\n\nPlease build the Daily Briefing."
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=DailyBriefing,
        ),
    )
    # response.parsed gives back a validated DailyBriefing object when
    # response_schema is set; fall back to manual parsing just in case.
    if getattr(response, "parsed", None) is not None:
        return response.parsed
    return DailyBriefing(**json.loads(response.text))
 
 
def generate_social_post(item: NewsItem, connection_idea: str, platform: str) -> str:
    """Second, separate Gemini call \u2014 fired only when a specific connection-idea
    button is clicked. Uses that one article + that one angle as the whole prompt,
    so the post stays tightly focused instead of a generic company blurb."""
    if platform == "LinkedIn":
        style_notes = (
            "LinkedIn tone: professional but personable, 3-5 short paragraphs or a short "
            "paragraph plus a few line breaks, can end with a light question or takeaway. "
            "Max 3 hashtags at the very end. Put the source link on its own line at the end."
        )
    else:
        style_notes = (
            "X (Twitter) tone: punchy, under 280 characters total including the link. "
            "No fluff, one clear point. Max 2 hashtags."
        )
 
    prompt = (
        f"Write a {platform} post for Heliofold US's company page about this news article, "
        f"built specifically around this angle: \"{connection_idea}\"\n\n"
        f"Article title: {item.title}\n"
        f"Article summary: {item.summary}\n"
        f"Source link: {item.link}\n\n"
        f"{style_notes}\n"
        "Voice: Heliofold US is a space-grade materials company (Ce-UTG cover glass, SCPI "
        "colorless polyimide film, HJT solar cells, DPA-8800/GPA-8811 adhesives), confident "
        "and technical but not salesy. No emojis unless it feels natural. Do not invent facts "
        "not in the article or summary. Output only the post text, nothing else."
    )
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.6),
    )
    return response.text.strip()
 
 
def item_key(item: NewsItem) -> str:
    """Stable short id per article, used to build unique Streamlit widget keys
    and to look up generated posts / watchlist matches."""
    return hashlib.md5(item.link.encode("utf-8")).hexdigest()[:10]
 
 
# ---------------------------------------------------------------------------
# Styling \u2014 overrides Streamlit's default look so the page reads less like
# a generic AI-generated tool and more like an internal Heliofold product.
# ---------------------------------------------------------------------------
 
def inject_style():
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
 
/* Hide Streamlit's default chrome so it doesn't read as a generic template */
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
  <p>Space materials &amp; market intelligence \u2014 internal use</p>
</div>
""",
        unsafe_allow_html=True,
    )
 
 
# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
 
def render_item(item: NewsItem, watchlist_by_title: dict, platform: str):
    accent = RATING_ACCENT.get(item.relevance_rating, "#999")
    label = RATING_LABEL.get(item.relevance_rating, "")
    matches = (watchlist_by_title or {}).get(item.title, [])
 
    key = item_key(item)
 
    st.markdown(f'<div class="hf-card" style="--accent:{accent};">', unsafe_allow_html=True)
 
    top_l, top_r = st.columns([4, 2])
    with top_l:
        st.markdown(f"<h4>{item.title}</h4>", unsafe_allow_html=True)
    with top_r:
        badges = f'<span class="hf-rating-tag">{label} \u00b7 {item.relevance_rating}/5</span>'
        if matches:
            match_labels = ", ".join(term for _cat, term in matches)
            badges = f'<span class="hf-watchlist-tag">Watchlist: {match_labels}</span> ' + badges
        st.markdown(f'<div style="text-align:right;">{badges}</div>', unsafe_allow_html=True)
 
    st.markdown(f"<p>{item.summary}</p>", unsafe_allow_html=True)
 
    if item.key_points:
        points_html = "".join(f"<li>{p}</li>" for p in item.key_points)
        st.markdown(f'<ul class="hf-keypoints">{points_html}</ul>', unsafe_allow_html=True)
 
    st.markdown(f'<p class="hf-reason">Why it matters: {item.relevance_reason}</p>', unsafe_allow_html=True)
    st.markdown(f'<a href="{item.link}" target="_blank" style="font-size:0.85em;">Read source \u2192</a>', unsafe_allow_html=True)
 
    if item.connection_ideas:
        with st.expander("5 ways this connects to Heliofold"):
            for idx, idea in enumerate(item.connection_ideas):
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(f"<span style='font-size:0.9em;'>{idx + 1}. {idea}</span>", unsafe_allow_html=True)
                with c2:
                    btn_key = f"draft_{key}_{idx}"
                    if st.button("Draft \u2192", key=btn_key):
                        with st.spinner(f"Writing {platform} post..."):
                            post_text = generate_social_post(item, idea, platform)
                            st.session_state.setdefault("generated_posts", {})[btn_key] = {
                                "text": post_text,
                                "platform": platform,
                            }
 
                generated = st.session_state.get("generated_posts", {}).get(btn_key)
                if generated:
                    st.caption(f"{generated['platform']} draft:")
                    st.code(generated["text"], language=None)
 
    st.markdown("</div>", unsafe_allow_html=True)
 
 
def render_briefing(briefing: DailyBriefing, watchlist_by_title: dict, platform: str):
    if briefing.top_priorities:
        st.markdown('<div class="hf-section-label">Top 3 Priorities Today</div>', unsafe_allow_html=True)
        for item in briefing.top_priorities:
            render_item(item, watchlist_by_title, platform)
 
    for section in briefing.sections:
        if not section.items:
            continue
        st.markdown(f'<div class="hf-section-label">{section.section_title}</div>', unsafe_allow_html=True)
        for item in section.items:
            render_item(item, watchlist_by_title, platform)
 
 
def briefing_to_plain_text(briefing: DailyBriefing) -> str:
    """Builds the plain-text version used for the PDF export, from the same
    structured data the website renders \u2014 so both stay in sync."""
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
    """Converts the plain-text report into a downloadable PDF format."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
 
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u2192": "->",
        "\u2605": "*", "\u2606": "-",
    }
    for orig, repl in replacements.items():
        report_text = report_text.replace(orig, repl)
 
    encoded_text = report_text.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 10, txt=encoded_text)
 
    return pdf.output(dest="S").encode("latin-1")
 
 
def main():
    st.set_page_config(page_title="Heliofold Daily Briefing", page_icon="\U0001F6F0\ufe0f", layout="wide")
    inject_style()
    render_masthead()
 
    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.write(
            "Pulls today's space, solar, and AI news, rates each item for relevance to "
            "Heliofold, and lets you draft ready-to-post LinkedIn or X content per article."
        )
    with top_r:
        platform = st.radio("Draft posts for", ["LinkedIn", "X"], horizontal=True, label_visibility="collapsed")
 
    if st.button("Generate Today's Report", type="primary"):
        with st.spinner("Compiling the day's news and writing the report..."):
 
            compiled_news = ""
            any_entries = False
            watchlist_by_title = {}  # title -> list of (category, term) matches
 
            for feed_url in FEEDS:
                entries = fetch_feed_entries(feed_url)
                for entry in entries:
                    any_entries = True
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
 
            if not any_entries:
                st.error("No articles could be fetched from any feed. Try again shortly.")
                return
 
            try:
                briefing = generate_daily_report(compiled_news)
                st.session_state["briefing"] = briefing
                st.session_state["watchlist_by_title"] = watchlist_by_title
                # Clear any previously generated posts from a prior day's report
                st.session_state["generated_posts"] = {}
            except Exception as e:
                st.error(f"Error generating report: {e}")
                return
 
    briefing: DailyBriefing = st.session_state.get("briefing")
    if briefing:
        watchlist_by_title = st.session_state.get("watchlist_by_title", {})
        render_briefing(briefing, watchlist_by_title, platform)
 
        plain_text = briefing_to_plain_text(briefing)
        pdf_bytes = create_pdf(plain_text)
 
        st.download_button(
            label="Download as PDF",
            data=pdf_bytes,
            file_name="Heliofold_Daily_Briefing.pdf",
            mime="application/pdf",
        )
 
 
if __name__ == "__main__":
    main()
 
