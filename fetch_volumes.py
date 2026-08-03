import requests, json, os, datetime
from requests.auth import HTTPBasicAuth

LOGIN = os.environ["DATAFORSEO_LOGIN"]
PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
KEYWORDS_FILE = "keywords.txt"
OUTPUT_FILE = "volumes.json"

LOCATION_CODE = 2528   # Netherlands
LANGUAGE_CODE = "nl"

URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"

# DataForSEO accepteert max. 1000 keywords per live-call, ruim genoeg hier.
BATCH_SIZE = 700


def fetch_batch(keywords):
    payload = [{
        "keywords": keywords,
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
    }]
    resp = requests.post(URL, auth=HTTPBasicAuth(LOGIN, PASSWORD), json=payload)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status_code") != 20000:
        print(f"WAARSCHUWING - globale fout: {data.get('status_message')}")

    volumes = {}
    for task in data.get("tasks", []):
        if task.get("status_code") != 20000:
            print(f"FOUT bij taak: {task.get('status_message')}")
            continue
        for item in task.get("result") or []:
            if item:
                volumes[item["keyword"]] = item.get("search_volume")
    return volumes


def main():
    with open(KEYWORDS_FILE) as f:
        keywords = [line.strip() for line in f if line.strip()]

    volumes = {}
    for i in range(0, len(keywords), BATCH_SIZE):
        batch = keywords[i:i + BATCH_SIZE]
        volumes.update(fetch_batch(batch))

    # keywords waar DataForSEO niets voor teruggaf (geen Ads-data) -> None
    for kw in keywords:
        volumes.setdefault(kw, None)

    today = datetime.date.today().isoformat()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "volumes": volumes}, f, ensure_ascii=False, indent=2)

    found = sum(1 for v in volumes.values() if v is not None)
    print(f"Klaar: {found}/{len(keywords)} keywords met zoekvolume opgehaald.")


if __name__ == "__main__":
    main()
