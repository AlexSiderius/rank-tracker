import requests, csv, json, os, time, datetime
from requests.auth import HTTPBasicAuth

LOGIN = os.environ["DATAFORSEO_LOGIN"]
PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
TARGET_DOMAIN = "webaware.nl"
KEYWORDS_FILE = "keywords.txt"
OUTPUT_FILE = "rankings.csv"
TOP10_FILE = "top10.json"   # actuele top 10 per keyword (wordt elke dag overschreven)

LOCATION_CODE = 2528   # Netherlands (heel land)
LANGUAGE_CODE = "nl"
SE_DOMAIN = "google.nl"  # expliciet google.nl i.p.v. de default google.com
DEVICE = "desktop"
DEPTH = 100            # top 100 resultaten i.p.v. 30, anders mis je posities 31-100

BASE_URL = "https://api.dataforseo.com/v3/serp/google/organic"


def submit_tasks(keywords):
    """Zet alle keywords in 1x klaar bij DataForSEO (Standard queue)."""
    payload = [
        {
            "keyword": kw,
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
            "se_domain": SE_DOMAIN,
            "device": DEVICE,
            "depth": DEPTH,
        }
        for kw in keywords
    ]
    resp = requests.post(
        f"{BASE_URL}/task_post",
        auth=HTTPBasicAuth(LOGIN, PASSWORD),
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status_code") != 20000:
        print(f"WAARSCHUWING - task_post gaf globale fout: {data.get('status_message')}")

    task_map = {}
    for task in data["tasks"]:
        kw = task["data"]["keyword"] if task.get("data") else "?"
        # bij task_post betekent status_code 20100 ("Task Created.") succes -
        # 20000 hoort bij voltooide resultaten (task_get), niet bij het aanmaken zelf
        if task.get("status_code") != 20100:
            print(f"FOUT bij indienen van '{kw}': {task.get('status_message')}")
            continue
        task_map[task["id"]] = kw
    return task_map


def wait_for_results(task_map, max_wait=900, poll_interval=20):
    """Poll totdat alle taken klaar zijn (Standard queue, kan bij grotere batches
    (60+ keywords) langer duren dan de oude 10 minuten)."""
    remaining = set(task_map.keys())
    results = {}
    waited = 0

    while remaining and waited < max_wait:
        resp = requests.get(
            f"{BASE_URL}/tasks_ready",
            auth=HTTPBasicAuth(LOGIN, PASSWORD),
        )
        resp.raise_for_status()
        ready_ids = {
            t["id"] for t in resp.json().get("tasks", [{}])[0].get("result") or []
        }
        for task_id in list(remaining):
            if task_id in ready_ids:
                results[task_id] = fetch_result(task_id)
                remaining.remove(task_id)

        if remaining:
            time.sleep(poll_interval)
            waited += poll_interval

    return results


def fetch_result(task_id):
    resp = requests.get(
        f"{BASE_URL}/task_get/regular/{task_id}",
        auth=HTTPBasicAuth(LOGIN, PASSWORD),
    )
    resp.raise_for_status()
    return resp.json()


def find_rank(result_json):
    try:
        items = result_json["tasks"][0]["result"][0]["items"]
    except (KeyError, IndexError, TypeError):
        return None, None
    for item in items:
        if item.get("type") == "organic" and TARGET_DOMAIN in item.get("domain", ""):
            return item.get("rank_absolute"), item.get("url")
    return None, None


def get_top10(result_json):
    try:
        items = result_json["tasks"][0]["result"][0]["items"]
    except (KeyError, IndexError, TypeError):
        return []
    organic = [i for i in items if i.get("type") == "organic"]
    top10 = []
    for item in organic[:10]:
        top10.append({
            "position": item.get("rank_absolute"),
            "title": item.get("title", ""),
            "domain": item.get("domain", ""),
            "url": item.get("url", ""),
            "is_target": TARGET_DOMAIN in item.get("domain", ""),
        })
    return top10


def main():
    with open(KEYWORDS_FILE) as f:
        keywords = [line.strip() for line in f if line.strip()]

    print(f"{len(keywords)} keywords indienen...")
    task_map = submit_tasks(keywords)

    if len(task_map) < len(keywords):
        print(f"LET OP: {len(keywords) - len(task_map)} van de {len(keywords)} taken konden niet worden ingediend (zie fouten hierboven).")

    print("Wachten op resultaten (Standard queue, kan enkele minuten duren)...")
    results = wait_for_results(task_map)

    today = datetime.date.today().isoformat()
    file_exists = os.path.exists(OUTPUT_FILE)
    top10_data = {}
    error_count = 0
    total = len(keywords)

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "keyword", "rank", "url"])

        for kw in keywords:
            task_id = next((tid for tid, k in task_map.items() if k == kw), None)

            if task_id is None:
                # kon niet eens worden ingediend (bv. saldo op)
                writer.writerow([today, kw, "error_submit", ""])
                top10_data[kw] = []
                error_count += 1
                continue

            result_json = results.get(task_id)
            if result_json is None:
                # kwam niet op tijd terug -> GEEN "not_found" schrijven, dat zou een valse
                # ranking-daling suggereren. Apart gemarkeerd zodat je het herkent.
                print(f"TIMEOUT: '{kw}' kreeg geen resultaat binnen de wachttijd.")
                writer.writerow([today, kw, "error_timeout", ""])
                top10_data[kw] = []
                error_count += 1
                continue

            task_result = (result_json.get("tasks") or [{}])[0]
            if task_result.get("status_code") != 20000:
                print(f"FOUT bij ophalen van '{kw}': {task_result.get('status_message')}")
                writer.writerow([today, kw, "error", ""])
                top10_data[kw] = []
                error_count += 1
                continue

            rank, url = find_rank(result_json)
            writer.writerow([today, kw, rank or "not_found", url or ""])
            print(f"{kw}: {rank or 'niet gevonden'}")
            top10_data[kw] = get_top10(result_json)

    with open(TOP10_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "results": top10_data}, f, ensure_ascii=False, indent=2)

    print(f"\nKlaar: {total - error_count}/{total} keywords succesvol verwerkt, {error_count} fouten/timeouts.")

    # als bijna alles faalt, laat de GitHub Actions run ook echt als 'mislukt' zien
    # i.p.v. stilletjes een CSV vol foutmeldingen weg te schrijven
    if total > 0 and error_count / total > 0.5:
        raise SystemExit(
            f"Meer dan de helft van de keywords ({error_count}/{total}) gaf een fout of timeout. "
            f"Check je DataForSEO-saldo en de foutmeldingen hierboven."
        )


if __name__ == "__main__":
    main()
