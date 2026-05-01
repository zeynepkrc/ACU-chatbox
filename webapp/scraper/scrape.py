from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
import csv

BASE = "https://obs.acibadem.edu.tr/oibs/bologna/"
LIST_URL = BASE + "unitSelection.aspx?type=lis&lang=tr"

SECTIONS = [
    "Eğitim Türü (Amaçlar) ve Hedefler",
    "Program Hakkında",
    "Program Profili",
    "Program Yetkilileri",
    "Alınacak Derece",
    "Kabul Koşulları",
    "Üst Kademeye Geçiş",
    "Mezuniyet Koşulları",
    "Önceki Öğrenmenin Tanınması",
    "Yeterlilik Koşulları ve Kuralları",
    "İstihdam Olanakları",
    "Program Yeterlikleri",
    "Dersler",
    "Ders & Program Yeterlilikleri İlişkisi",
    "TYYÇ - Program Yeterlilikleri İlişkisi",
    "Akademik Personel",
    "İletişim",
]

MENU_WORDS = [
    "Bilgi Paketi",
    "Kurumsal Bilgiler",
    "Akademik Birimler",
    "Öğrenciler İçin Genel Bilgiler",
    "Erasmus Beyannamesi",
    "Bologna Süreci",
    "www.prolizyazilim.com",
]

def clean_text(text):
    return " ".join(text.split())

def is_bad_menu_text(text):
    text = clean_text(text)
    count = sum(1 for w in MENU_WORDS if w in text)
    return text.startswith("Bilgi Paketi") and count >= 4

def collect_text_candidates(driver):
    candidates = []

    # aktif sayfadaki tüm görünür textleri al
    try:
        texts = driver.execute_script("""
        const arr = [];
        const els = document.querySelectorAll("body, div, table, tbody, tr, td, span, p");
        for (const el of els) {
            const style = window.getComputedStyle(el);
            const txt = (el.innerText || "").trim();

            if (
                txt.length > 40 &&
                style.display !== "none" &&
                style.visibility !== "hidden"
            ) {
                arr.push(txt);
            }
        }
        return arr;
        """)
        candidates.extend(texts)
    except:
        pass

    # iframe varsa onların içini de gez
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(len(frames)):
            try:
                driver.switch_to.frame(frames[i])

                texts = driver.execute_script("""
                const arr = [];
                const els = document.querySelectorAll("body, div, table, tbody, tr, td, span, p");
                for (const el of els) {
                    const style = window.getComputedStyle(el);
                    const txt = (el.innerText || "").trim();

                    if (
                        txt.length > 40 &&
                        style.display !== "none" &&
                        style.visibility !== "hidden"
                    ) {
                        arr.push(txt);
                    }
                }
                return arr;
                """)
                candidates.extend(texts)

                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
    except:
        pass

    clean_candidates = []
    seen = set()

    for c in candidates:
        c = clean_text(c)
        if c and c not in seen:
            clean_candidates.append(c)
            seen.add(c)

    return clean_candidates

def get_best_content(driver, section):
    candidates = collect_text_candidates(driver)

    good = []

    for text in candidates:
        if is_bad_menu_text(text):
            continue

        score = len(text)

        if section in text:
            score += 2000

        if text.startswith(section):
            score += 3000

        # Menü metniyse puan kır
        for w in MENU_WORDS:
            if w in text:
                score -= 500

        good.append((score, text))

    if not good:
        return ""

    good.sort(reverse=True, key=lambda x: x[0])
    return good[0][1]

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

# 1) Lisans programlarını bul
driver.get(LIST_URL)
time.sleep(4)

programs = []

for el in driver.find_elements(By.TAG_NAME, "a"):
    text = clean_text(el.text)
    href = el.get_attribute("href")

    if text and href and "curUnit" in href and "curSunit" in href:
        programs.append({
            "degree_type": "Lisans",
            "program": text,
            "url": href
        })

unique_programs = []
seen = set()

for p in programs:
    if p["url"] not in seen:
        unique_programs.append(p)
        seen.add(p["url"])

print(f"{len(unique_programs)} lisans programı bulundu.")

data = []

# 2) Her lisans programında her başlığı tıkla
for prog in unique_programs:
    print("\nBölüm:", prog["program"])

    for section in SECTIONS:
        try:
            driver.get(prog["url"])
            time.sleep(3)

            el = driver.find_element(By.LINK_TEXT, section)
            driver.execute_script("arguments[0].click();", el)
            time.sleep(4)

            content = get_best_content(driver, section)

            if not content or is_bad_menu_text(content):
                print("  ❌ alınamadı:", section, "|", content[:80])
            else:
                print("  ✔", section, "|", content[:120])

            data.append({
                "degree_type": prog["degree_type"],
                "program": prog["program"],
                "section": section,
                "url": driver.current_url,
                "content": content
            })

        except Exception as e:
            print("  Hata:", section, e)

df = pd.DataFrame(data)

df.to_csv(
    "bologna_lisans_programs_full.csv",
    index=False,
    sep="|",
    encoding="utf-8-sig",
    quoting=csv.QUOTE_ALL
)

driver.quit()

print("Bitti. bologna_lisans_programs_full.csv oluşturuldu.")