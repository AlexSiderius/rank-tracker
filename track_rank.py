import requests, csv, os, time, datetime
from requests.auth import HTTPBasicAuth

LOGIN = os.environ["DATAFORSEO_LOGIN"]
PASSWORD = os.environ["DATAFORSEO_PASSWORD"]
TARGET_DOMAIN = "webaware.nl"
KEYWORDS_FILE = "keywords.txt"
OUTPUT_FILE = "rankings.csv"

LOCATION_CODE = 2528   # Netherlands (heel land)
LANGUAGE_CODE = "nl"
DEPTH = 30             # top 30 resultaten

BASE_URL = "https://api.dataforseo.com/v3/serp/google/organic"


def submit_tasks(keywords):
    """Zet alle keywords in 1x klaar bij DataForSEO (Standard queue)."""
    payload = [
        {
            "keyword": kw,
            "location_code": LOCATION_CODE,
            "language_code": LANGUAGE_CODE,
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
    # koppel elke task_id terug aan het bijbehorende keyword
    task_map = {}
    for task in data["tasks"]:
        kw = task["data"]["keyword"]
        task_map[task["id"]] = kw
    return task_map


def wait_for_results(task_map, max_wait=600, poll_interval=20):
    """Poll totdat alle taken klaar zijn (Standard queue ~5 min)."""
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
        return None
    for item in items:
        if item.get("type") == "organic" and TARGET_DOMAIN in item.get("domain", ""):
            return item.get("rank_absolute")
    return None


def main():
    with open(KEYWORDS_FILE) as f:
        keywords = [line.strip() for line in f if line.strip()]

    print(f"{len(keywords)} keywords indienen...")
    task_map = submit_tasks(keywords)

    print("Wachten op resultaten (Standard queue, kan enkele minuten duren)...")
    results = wait_for_results(task_map)

    today = datetime.date.today().isoformat()
    file_exists = os.path.exists(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "keyword", "rank"])
        for task_id, kw in task_map.items():
            result_json = results.get(task_id)
            rank = find_rank(result_json) if result_json else None
            writer.writerow([today, kw, rank or "not_found"])
            print(f"{kw}: {rank or 'niet gevonden'}")


if __name__ == "__main__":
    main()
