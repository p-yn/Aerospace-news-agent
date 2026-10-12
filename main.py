import hashlib
import json
import os
import time
from datetime import datetime
from typing import List

import pytz
import streamlit as st
from fpdf import FPDF
from google import genai
from google.genai import types
from pydantic import BaseModel

# Pull the API key from Streamlit's secure secrets manager
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# ---------------------------------------------------------------------------
# Configuration & Storage
# ---------------------------------------------------------------------------
REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_briefing.json")
LOCAL_TIMEZONE = "America/Vancouver"

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

RATING_LABEL = {5: "Critical", 4: "High", 3: "Moderate", 2: "Low", 1: "Background"}
RATING_ACCENT = {5: "#8a1f2d", 4: "#b9862f", 3: "#5c6b73", 2: "#8a8a8a", 1: "#bcbcbc"}
BRAND_NAVY = "#0b1f3a"
BRAND_GOLD = "#c9a227"

def generate_social_post(item: NewsItem, connection_idea: str, platform: str) -> str:
    if platform == "LinkedIn":
        style_notes = (
           "LinkedIn Guidelines (Maximum 100 words):\n"
"Follow this structure, in order:\n"
"1. Hook: A non-technical, concrete news hook, an industry milestone, launch, or announcement. Prefer specific numbers/milestones (e.g. '100th launch this year') over abstract big numbers (e.g. '$100B expansion'), concrete milestones perform better. The first line must be a strong stopper on its own, LinkedIn truncates after 2-3 lines, so it needs to earn the 'see more' click without relying on what follows.\n"
"2. Reframe: One sentence that reframes the news into a sharp, non-obvious insight. Avoid generic causal chains like 'more launches → satellites need power → we make power systems,' which could apply to almost any component. The reframe should say something a reader wouldn't have already assumed.\n"
"3. Technical differentiator: One clear, specific claim about Bifacia (or the relevant product), tied directly back to the stress or problem named in the hook. Name the actual mechanism, dual-sided power collection, thermal stability, mass savings, not just 'our product is great.' Whenever naturally relevant, connect the development to Heliofold US this way. If the news is genuinely unrelated to our space, do not force a connection, end with a relevant industry takeaway instead.\n"
"4. CTA: Short, with a specific next step, not vague curiosity-bait. 'Send us your stack spec, we'll tell you the wattage gain' is better than 'Curious how this fits your next batch?'\n\n"
"Formatting rules:\n"
"- Links go in the first comment, never in the post body. Note the source link separately so it can be posted as a reply.\n"
"- Max 3 hashtags, and each must add distinct value, don't duplicate near-synonyms (e.g. not both #SpaceInfrastructure and #SpaceSolar in the same post).\n\n"
"Before finalizing, check:\n"
"- Does the hook use a concrete number/milestone rather than an abstract one?\n"
"- Does the reframe say something non-obvious, not just a logical restatement?\n"
"- Is the technical claim tied specifically to the problem named in the hook, not generic?\n"
"- Is the CTA a specific action, not just a question?\n"
"- Is there exactly one link (flagged separately for the comment) and ≤3 non-redundant hashtags?\n\n"
"Tone: Professional but human, written from the perspective of Paul Zhu, International Project Director at Heliofold. Avoid excessive emojis and generic corporate language. Never make unsupported claims about Heliofold."
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
def load_latest_report():
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
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

    st.write(
        "Displays the daily space, solar, and AI briefing generated independently by GitHub Actions, "
        "and lets you draft ready-to-post LinkedIn or X content from key topics."
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
        st.warning(
            "No report is available yet. The daily report is generated by GitHub Actions; "
            "check the repository's Actions tab if it has not appeared."
        )

if __name__ == "__main__":
    main()