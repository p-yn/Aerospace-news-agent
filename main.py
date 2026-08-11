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
# Structured output schema
# Using a schema (instead of free text) means the website can render clean
# sections/cards and the PDF is built from the same reliable data, instead of
# trying to parse formatting out of loose AI-generated text.
# ---------------------------------------------------------------------------
 
class NewsItem(BaseModel):
    title: str
    summary: str
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
    "constellation operators, university satellite programs, and space agencies.\n\n"
    "I will give you a list of today's aerospace, solar, and AI news. Read all of it and "
    "organize it into a Daily Briefing using the required JSON schema. Rules:\n"
    "1. Group items into sections such as Satellite & Spacecraft, Solar & Materials, "
    "AI & Autonomy, Industry & Funding \u2014 only include sections that have items.\n"
    "2. Each item's summary should be 2-3 plain-text sentences, no markdown formatting.\n"
    "3. Rate every item's relevance to Heliofold from 1 to 5: "
    "5 = directly actionable (a named potential customer, competitor, or supply chain event), "
    "4 = strong strategic relevance (market trend directly touching Heliofold's product lines), "
    "3 = moderately relevant (general space/solar industry movement worth awareness), "
    "2 = tangential (adjacent field, limited direct impact), "
    "1 = background noise (interesting but not actionable for Heliofold).\n"
    "4. Give a one-sentence reason for each rating.\n"
    "5. Always include the original URL exactly as provided.\n"
    "6. In top_priorities, list only the 3 highest-rated items across the whole briefing, "
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
 
RATING_LABEL = {
    5: "Critical",
    4: "High",
    3: "Moderate",
    2: "Low",
    1: "Background",
}
 
RATING_COLOR = {
    5: "#1a7f37",  # green
    4: "#4c9a2a",
    3: "#c9a227",  # amber
    2: "#c97a27",
    1: "#8a8a8a",  # gray
}
 
 
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
 
 
# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
 
def render_item(item: NewsItem):
    color = RATING_COLOR.get(item.relevance_rating, "#8a8a8a")
    label = RATING_LABEL.get(item.relevance_rating, "")
    stars = "\u2605" * item.relevance_rating + "\u2606" * (5 - item.relevance_rating)
 
    st.markdown(
        f"""
<div style="border:1px solid #333; border-radius:10px; padding:14px 16px; margin-bottom:12px;">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
    <span style="font-weight:600; font-size:1.05em;">{item.title}</span>
    <span style="background:{color}; color:white; border-radius:6px; padding:2px 8px; font-size:0.8em; white-space:nowrap;">
      {stars} {label}
    </span>
  </div>
  <p style="margin:8px 0 6px 0;">{item.summary}</p>
  <p style="margin:0; font-size:0.85em; color:#999;">Why it matters: {item.relevance_reason}</p>
  <a href="{item.link}" target="_blank" style="font-size:0.85em;">Read source \u2192</a>
</div>
""",
        unsafe_allow_html=True,
    )
 
 
def render_briefing(briefing: DailyBriefing):
    if briefing.top_priorities:
        st.subheader("\U0001F3AF Top 3 Priorities Today")
        for item in briefing.top_priorities:
            render_item(item)
        st.divider()
 
    for section in briefing.sections:
        if not section.items:
            continue
        st.subheader(section.section_title)
        for item in section.items:
            render_item(item)
 
 
def briefing_to_plain_text(briefing: DailyBriefing) -> str:
    """Builds the plain-text version used for the PDF export, from the same
    structured data the website renders \u2014 so both stay in sync."""
    lines = []
 
    if briefing.top_priorities:
        lines.append("TOP 3 PRIORITIES TODAY")
        lines.append("")
        for item in briefing.top_priorities:
            lines.append(item.title)
            lines.append(item.summary)
            lines.append(f"Heliofold Relevance: {item.relevance_rating}/5 - {item.relevance_reason}")
            lines.append(item.link)
            lines.append("")
        lines.append("")
 
    for section in briefing.sections:
        if not section.items:
            continue
        lines.append(section.section_title.upper())
        lines.append("")
        for item in section.items:
            lines.append(item.title)
            lines.append(item.summary)
            lines.append(f"Heliofold Relevance: {item.relevance_rating}/5 - {item.relevance_reason}")
            lines.append(item.link)
            lines.append("")
        lines.append("")
 
    return "\n".join(lines)
 
 
def create_pdf(report_text: str) -> bytes:
    """Converts the plain-text report into a downloadable PDF format."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
 
    # Replace common non-latin-1 characters (smart quotes, em/en dashes,
    # ellipsis, arrows) before falling back to '?'
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
    st.set_page_config(page_title="Heliofold News Agent", page_icon="\U0001F6F0\ufe0f", layout="wide")
    st.title("\U0001F6F0\ufe0f Heliofold Daily Briefing")
    st.write(
        "Click below to pull today's space, solar, and AI news, rate each item for "
        "relevance to Heliofold, and generate a downloadable PDF for LinkedIn."
    )
 
    if st.button("Generate Today's Report", type="primary"):
        with st.spinner("Compiling the day's news and writing the report..."):
 
            compiled_news = ""
            any_entries = False
            for feed_url in FEEDS:
                entries = fetch_feed_entries(feed_url)
                for entry in entries:
                    any_entries = True
                    title = entry.get("title", "No Title")
                    link = entry.get("link", "")
                    summary_html = entry.get("summary", "")
                    clean_summary = clean_html(summary_html)
 
                    compiled_news += f"Title: {title}\nSummary: {clean_summary}\nLink: {link}\n\n"
 
            if not any_entries:
                st.error("No articles could be fetched from any feed. Try again shortly.")
                return
 
            try:
                briefing = generate_daily_report(compiled_news)
                st.session_state["briefing"] = briefing
            except Exception as e:
                st.error(f"Error generating report: {e}")
                return
 
    # Render whatever briefing we have (persists across reruns via session_state)
    briefing: DailyBriefing = st.session_state.get("briefing")
    if briefing:
        st.success("Report ready.")
        render_briefing(briefing)
 
        plain_text = briefing_to_plain_text(briefing)
        pdf_bytes = create_pdf(plain_text)
 
        st.download_button(
            label="Download as PDF for LinkedIn",
            data=pdf_bytes,
            file_name="Heliofold_Daily_Briefing.pdf",
            mime="application/pdf",
        )
 
 
if __name__ == "__main__":
    main()
