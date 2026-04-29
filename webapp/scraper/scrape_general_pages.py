import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

BASE = "https://obs.acibadem.edu.tr/oibs/bologna/"

GENERAL_PAGES = [
    {"category": "Kurumsal Bilgiler", "title": "Sayfa 100", "url": BASE + "dynConPage.aspx?curPageId=100&lang=tr"},
    {"category": "Kurumsal Bilgiler", "title": "Sayfa 101", "url": BASE + "dynConPage.aspx?curPageId=101&lang=tr"},
    {"category": "Kurumsal Bilgiler", "title": "Sayfa 102", "url": BASE + "dynConPage.aspx?curPageId=102&lang=tr"},
    {"category": "Kurumsal Bilgiler", "title": "Sayfa 103", "url": BASE + "dynConPage.aspx?curPageId=103&lang=tr"},
    {"category": "Kurumsal Bilgiler", "title": "Sayfa 104", "url": BASE + "dynConPage.aspx?curPageId=104&lang=tr"},

    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 300", "url": BASE + "dynConPage.aspx?curPageId=300&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 301", "url": BASE + "dynConPage.aspx?curPageId=301&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 302", "url": BASE + "dynConPage.aspx?curPageId=302&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 303", "url": BASE + "dynConPage.aspx?curPageId=303&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 304", "url": BASE + "dynConPage.aspx?curPageId=304&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 305", "url": BASE + "dynConPage.aspx?curPageId=305&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 309", "url": BASE + "dynConPage.aspx?curPageId=309&lang=tr"},
    {"category": "Öğrenciler İçin Genel Bilgiler", "title": "Sayfa 311", "url": BASE + "dynConPage.aspx?curPageId=311&lang=tr"},

    {"category": "Erasmus Beyannamesi", "title": "Erasmus Beyannamesi", "url": BASE + "dynConPage.aspx?curPageId=401&lang=tr"},
    {"category": "Bologna Süreci", "title": "Bologna Süreci", "url": BASE + "dynConPage.aspx?curPageId=400&lang=tr"},
]

def clean_text(text):
    return " ".join(text.split())

data = []

for page in GENERAL_PAGES:
    print("Alınıyor:", page["category"], "-", page["title"])

    try:
        res = requests.get(page["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        content = clean_text(soup.get_text(" "))

        data.append({
            "type": "general_bologna",
            "category": page["category"],
            "title": page["title"],
            "url": page["url"],
            "content": content
        })

        time.sleep(1)

    except Exception as e:
        print("Hata:", page["title"], e)

df = pd.DataFrame(data)
df.to_csv("bologna_general_pages.csv", index=False, encoding="utf-8-sig")

print("Bitti. bologna_general_pages.csv oluşturuldu.")