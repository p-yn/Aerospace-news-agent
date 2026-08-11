import feedparser
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import streamlit as st
from fpdf import FPDF

# Pull the API key from Streamlit's secure secrets manager
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

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
    "write a 'Daily Briefing' report with these rules:\n"
    "1. Group items under clear headings (e.g. Satellite & Spacecraft, Solar & Materials, "
    "AI & Autonomy, Industry & Funding).\n"
    "2. For each news item, write 2-3 sentences summarizing it in plain text, no markdown "
    "bolding or asterisks.\n"
    "3. Immediately after each item's summary, include a line in this exact format: "
    "'Heliofold Relevance: [X/5] - [one sentence reason]' where X is your rating of how "
    "useful or relevant this news is to Heliofold's business, sourcing strategy, product "
    "roadmap, or customer targets. Use this scale: "
    "5 = directly actionable (a named potential customer, competitor, or supply chain event), "
    "4 = strong strategic relevance (market trend directly touching Heliofold's product lines), "
    "3 = moderately relevant (general space/solar industry movement worth awareness), "
    "2 = tangential (adjacent field, limited direct impact), "
    "1 = background noise (interesting but not actionable for Heliofold).\n"
    "4. CRITICAL: For every news item you mention, you MUST include the original URL link "
    "provided in the prompt.\n"
    "5. At the very end, add a short 'Top 3 Priorities Today' section listing only the "
    "3 highest-rated items across the whole briefing, in order."
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


def generate_daily_report(all_news_text):
    prompt = f"Here is today's news:\n\n{all_news_text}\n\nPlease write the Daily Briefing."
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
        )
    )
    return response.text


def create_pdf(report_text):
    """Converts the text report into a downloadable PDF format."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Replace common non-latin-1 characters Gemini tends to produce
    # (smart quotes, em/en dashes, ellipsis) before falling back to '?'
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...",
    }
    for orig, repl in replacements.items():
        report_text = report_text.replace(orig, repl)

    encoded_text = report_text.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=encoded_text)

    # Return the PDF as a byte string so Streamlit can download it
    return pdf.output(dest='S').encode('latin-1')


def main():
    st.set_page_config(page_title="Heliofold News Agent", page_icon="🛰️")
    st.title("🛰️ Heliofold Daily Briefing")
    st.write("Click below to generate a cohesive daily report, rated for relevance to "
              "Heliofold, and download it as a PDF for LinkedIn.")

    if st.button("Generate Today's Report"):
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
                final_report = generate_daily_report(compiled_news)
                st.success("Report Generated!")

                # Show the text area so you can edit it before making the PDF
                edited_report = st.text_area("Review your report:", value=final_report, height=400)

                # Generate the PDF bytes
                pdf_bytes = create_pdf(edited_report)

                # The magical Streamlit Download Button!
                st.download_button(
                    label="Download as PDF for LinkedIn",
                    data=pdf_bytes,
                    file_name="Heliofold_Daily_Briefing.pdf",
                    mime="application/pdf"
                )

            except Exception as e:
                st.error(f"Error generating report: {e}")


if __name__ == "__main__":
    main()
