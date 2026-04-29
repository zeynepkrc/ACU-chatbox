from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import pandas as pd

BASE = "https://obs.acibadem.edu.tr/oibs/bologna/"

PROGRAM_TYPES = {
    "lis": "Lisans",
   
}

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

program_links = []

# 1) Ön Lisans + Lisans + Yüksek Lisans + Doktora programlarını topla
for type_code, type_name in PROGRAM_TYPES.items():
    url = BASE + f"unitSelection.aspx?type={type_code}&lang=tr"
    print("Program türü açılıyor:", type_name)

    driver.get(url)
    time.sleep(4)

    elements = driver.find_elements(By.TAG_NAME, "a")

    for el in elements:
        href = el.get_attribute("href")
        text = el.text.strip()

        if href and "curUnit" in href and "curSunit" in href:
            program_links.append({
                "degree_type": type_name,
                "program": text,
                "url": href
            })

print(f"{len(program_links)} program bulundu.")

data = []

# 2) Her programın Bologna sekmelerini scrape et
for prog in program_links:
    print("\nBölüm:", prog["degree_type"], "-", prog["program"])

    try:
        driver.get(prog["url"])
        time.sleep(3)

        menu_items = driver.find_elements(By.TAG_NAME, "a")

        menu_texts = []
        for m in menu_items:
            t = m.text.strip()
            if t:
                menu_texts.append(t)

        menu_texts = list(dict.fromkeys(menu_texts))

        for section in menu_texts:
            try:
                driver.get(prog["url"])
                time.sleep(2)

                el = driver.find_element(By.LINK_TEXT, section)
                driver.execute_script("arguments[0].click();", el)
                time.sleep(3)

                content = driver.find_element(By.TAG_NAME, "body").text

                data.append({
                    "degree_type": prog["degree_type"],
                    "program": prog["program"],
                    "section": section,
                    "url": driver.current_url,
                    "content": content
                })

                print("  ✔", section)

            except Exception:
                pass

    except Exception as e:
        print("Hata:", prog["program"], e)

df = pd.DataFrame(data)
df.to_csv("bologna_all_degree_programs.csv", index=False, encoding="utf-8-sig")

driver.quit()

print("Bitti. bologna_all_degree_programs.csv oluşturuldu.")