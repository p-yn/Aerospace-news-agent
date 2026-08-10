import feedparser
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import streamlit as st

# Pull the API key from Streamlit's secure secrets manager
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

system_instruction = (
    "You are an expert social media manager for Heliofold US. "
    "Heliofold specializes in space solar technology, flexible solar arrays, "
    "colorless polyimide film, ultra-thin cover glass, and polyamic acid supply chains. "
    "I will provide you with a list of today's top aerospace, solar, and AI news. "
    "Your job is to read them all and write a cohesive, well-written 'Daily Briefing' report "
    "that highlights only the most relevant developments for our audience. "
    "Write it in an engaging, professional tone suitable for LinkedIn or X, using clear headings and bullet points."
)

FEEDS = [
    "https://spacenews.com/feed/",                                          
    "https://techcrunch.com/category/artificial-intelligence/feed/",        
    "https://www.solarpowerworldonline.com/feed/"                           
]

def clean_html(raw_html):
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)

def generate_daily_report(all_news_text):
    prompt = f"Here is today's news:\n\n{all_news_text}\n\nPlease write the Daily Briefing."
    response = client.models.generate_content(
        model='gemini-3.6-flash', # <--- Updated to the correct model!
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
        )
    )
    return response.text

def main():
    st.set_page_config(page_title="Heliofold News Agent", page_icon="🛰️")
    st.title("🛰️ Heliofold Daily Briefing")
    st.write("Click below to generate a cohesive daily report from today's top industry news.")
    
    if st.button("Generate Today's Report"):
        with st.spinner('Compiling the day\'s news and writing the report...'):
            
            # Step A: Gather all the news into one big string
            compiled_news = ""
            for feed_url in FEEDS:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:4]: # Grabbing top 4 from each
                    title = entry.get("title", "No Title")
                    link = entry.get("link", "")
                    summary_html = entry.get("summary", "")
                    clean_summary = clean_html(summary_html)
                    
                    compiled_news += f"Title: {title}\nSummary: {clean_summary}\nLink: {link}\n\n"
            
            # Step B: Send the giant string to the AI to write the final report (Only ONE request!)
            try:
                final_report = generate_daily_report(compiled_news)
                st.success("Report Generated!")
                st.markdown(final_report)
            except Exception as e:
                st.error(f"Error generating report: {e}")

if __name__ == "__main__":
    main()