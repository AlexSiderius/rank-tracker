import requests, json, os, re, datetime
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


def clean_keyword(kw):
    """De Google Ads volume-API accepteert geen leestekens zoals '?', '!', ':'.
    We strippen alles behalve letters, cijfers, spaties en koppeltekens, en
    sturen dat naar de API - de originele keyword-tekst blijft de sleutel
    in volumes.json, zodat de match met rankings.csv/keywords.txt klopt."""
    cleaned = re.sub(r"[^\w\s\-]", " ", kw, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def fetch_batch(clean_to_originals):
    """clean_to_originals: dict van opgeschoonde keyword-tekst -> lijst met
    originele keyword(s) uit keywords.txt die daarnaar opschonen."""
    clean_keywords = list(clean_to_originals.keys())
    payload = [{
        "keywords": clean_keywords,
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
            if not item:
                continue
            for original in clean_to_originals.get(item["keyword"], []):
                volumes[original] = item.get("search_volume")
    return volumes


def main():
    with open(KEYWORDS_FILE) as f:
        keywords = [line.strip() for line in f if line.strip()]

    # groepeer originele keywords per opgeschoonde variant (kan dubbel voorkomen,
    # bv. met/zonder vraagteken -> dezelfde clean tekst, beide moeten een volume krijgen)
    clean_to_originals = {}
    for kw in keywords:
        clean_to_originals.setdefault(clean_keyword(kw), []).append(kw)

    clean_items = list(clean_to_originals.items())
    volumes = {}
    for i in range(0, len(clean_items), BATCH_SIZE):
        batch = dict(clean_items[i:i + BATCH_SIZE])
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
