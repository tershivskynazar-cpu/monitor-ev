import csv
import json
import os
import sys
import time
from datetime import datetime
from collections import defaultdict

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# EVBOOST public location IDs supplied in this chat.
STATIONS = {
    12095: "Ралівка",
    30663: "Турка",
    12015: "Дрогобич",
}

INTERVAL_SECONDS = 5 * 60
DATA_FILE = os.getenv("EVBOOST_DATA_FILE", "data/evboost_history.csv")
REPORT_FILE = os.getenv("EVBOOST_REPORT_FILE", "data/evboost_report.txt")
TIMEOUT = 20

# We keep the raw status code. Based on the examples supplied by the user,
# status 1 is displayed by EVBOOST as FREE. Other codes are not silently
# converted into "busy" because the public response does not document them.
STATUS_LABELS = {
    1: "FREE",
    2: "CHARGING",
    3: "FINISHING",
    4: "OTHER/OFFLINE",
}


def api_url(station_id):
    return f"https://www.evboost.com.ua/api/get_chargers_info_by_location/{station_id}"


def fetch_station(station_id):
    r = requests.get(
        api_url(station_id),
        timeout=TIMEOUT,
        headers={"User-Agent": "EVBOOST-monitor/1.0"},
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or "chargers" not in data:
        raise ValueError("Unexpected EVBOOST response")
    return data


def label(code):
    return STATUS_LABELS.get(code, f"STATUS_{code}")


def init_csv():
    data_dir = os.path.dirname(DATA_FILE)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)

    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        return
    with open(DATA_FILE, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            "timestamp", "station", "station_id", "station_online",
            "charger_id", "connector", "power_kw", "status_code",
            "status", "soc_percent", "price_uah_kwh"
        ])


def collect_once(verbose=True):
    init_csv()
    now = datetime.now().replace(microsecond=0)
    rows = []
    snapshot = []

    for station_id, station_name in STATIONS.items():
        try:
            data = fetch_station(station_id)
            online = data.get("isOnline")
            chargers = data.get("chargers", [])

            for c in chargers:
                code = c.get("chargerStatus")
                row = [
                    now.isoformat(sep=" "),
                    station_name,
                    station_id,
                    online,
                    c.get("id"),
                    c.get("alias"),
                    c.get("power"),
                    code,
                    label(code),
                    c.get("socPercent"),
                    c.get("price"),
                ]
                rows.append(row)
                snapshot.append(row)

            if verbose:
                print(f"\n{station_name} | online={online}")
                for c in chargers:
                    print(
                        f"  {c.get('alias','?'):10} "
                        f"{str(c.get('power','?')):>4} kW  "
                        f"{label(c.get('chargerStatus')):14} "
                        f"SOC={c.get('socPercent')}"
                    )

        except Exception as e:
            if verbose:
                print(f"\n{station_name}: ERROR - {e}")

    with open(DATA_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)

    return snapshot


def parse_dt(s):
    return datetime.fromisoformat(s)


def load_rows():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def status_stats(rows):
    stats = defaultdict(lambda: {
        "samples": 0,
        "free": 0,
        "charging": 0,
        "other": 0,
        "online_samples": 0,
        "soc_values": [],
    })

    for r in rows:
        key = (r["station"], r["connector"])
        s = stats[key]
        s["samples"] += 1

        if str(r["station_online"]).lower() == "true":
            s["online_samples"] += 1

        code = r["status_code"]
        if code == "1":
            s["free"] += 1
        elif code == "2":
            s["charging"] += 1
        else:
            s["other"] += 1

        if r["soc_percent"] not in ("", "None", "null"):
            try:
                s["soc_values"].append(float(r["soc_percent"]))
            except ValueError:
                pass

    return stats


def make_report():
    rows = load_rows()
    if not rows:
        print("Ще немає даних. Спочатку запусти збір.")
        return

    stats = status_stats(rows)
    first = min(parse_dt(r["timestamp"]) for r in rows)
    last = max(parse_dt(r["timestamp"]) for r in rows)

    lines = []
    lines.append("=" * 78)
    lines.append("EVBOOST — ДЕТАЛЬНА СТАТИСТИКА")
    lines.append("=" * 78)
    lines.append(f"Період: {first}  →  {last}")
    lines.append(f"Знімків у CSV: {len(rows)}")
    lines.append(f"Інтервал збору: {INTERVAL_SECONDS // 60} хв")
    lines.append("")

    # Per station summary
    for station_id, station_name in STATIONS.items():
        station_rows = [r for r in rows if r["station_id"] == str(station_id)]
        if not station_rows:
            continue

        lines.append("-" * 78)
        lines.append(f"{station_name} (ID {station_id})")
        lines.append("-" * 78)

        connectors = sorted(set(r["connector"] for r in station_rows))
        for connector in connectors:
            key = (station_name, connector)
            s = stats[key]
            n = s["samples"] or 1
            free_pct = s["free"] / n * 100
            charging_pct = s["charging"] / n * 100
            other_pct = s["other"] / n * 100
            online_pct = s["online_samples"] / n * 100

            # This is "observed time" based on sampling interval, not an exact
            # session duration. The last sample is not extended beyond itself.
            observed_h = s["samples"] * INTERVAL_SECONDS / 3600
            free_h = s["free"] * INTERVAL_SECONDS / 3600
            charging_h = s["charging"] * INTERVAL_SECONDS / 3600
            other_h = s["other"] * INTERVAL_SECONDS / 3600

            avg_soc = (
                sum(s["soc_values"]) / len(s["soc_values"])
                if s["soc_values"] else None
            )

            lines.append(
                f"{connector}: "
                f"FREE {free_pct:5.1f}% ({free_h:6.2f} h) | "
                f"CHARGING {charging_pct:5.1f}% ({charging_h:6.2f} h) | "
                f"OTHER {other_pct:5.1f}% ({other_h:6.2f} h) | "
                f"online {online_pct:5.1f}%"
            )
            lines.append(
                f"    samples={s['samples']}, "
                f"power examples from raw CSV, "
                f"avg SOC={avg_soc:.1f}%" if avg_soc is not None
                else f"    samples={s['samples']}, avg SOC=N/A"
            )

        # station-wide snapshot occupancy
        lines.append("")
        lines.append("Поточний останній відомий стан:")
        latest_time = max(parse_dt(r["timestamp"]) for r in station_rows)
        latest = [
            r for r in station_rows if parse_dt(r["timestamp"]) == latest_time
        ]
        for r in latest:
            lines.append(
                f"    {r['connector']}: {r['status']} "
                f"({r['power_kw']} kW), SOC={r['soc_percent']}"
            )

    lines.append("")
    lines.append("-" * 78)
    lines.append("ВАЖЛИВО")
    lines.append("-" * 78)
    lines.append(
        "Статистика часу є оцінкою за інтервалом опитування. "
        "Вона не є точною тривалістю сесій."
    )
    lines.append(
        "EVBOOST попереджає, що статуси/доступність можуть мати затримки "
        "або помилки; тому дані краще використовувати для статистики, "
        "а не як гарантію доступності зарядки."
    )

    report = "\n".join(lines)
    report_dir = os.path.dirname(REPORT_FILE)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + report)
    print(f"\nЗвіт збережено: {REPORT_FILE}")


def run_loop():
    print("\nЗбір запущено. Ctrl+C — зупинити.")
    while True:
        started = time.time()
        try:
            collect_once(verbose=True)
        except KeyboardInterrupt:
            print("\nЗупинено.")
            break
        except Exception as e:
            print("Помилка циклу:", e)

        elapsed = time.time() - started
        time.sleep(max(1, INTERVAL_SECONDS - elapsed))


def interactive_main():
    print("EVBOOST Monitor")
    print("Станції: Ралівка, Турка, Дрогобич")
    print("Збір кожні 5 хвилин.")
    print("")
    print("1 — збирати дані")
    print("2 — показати статистику")
    print("3 — зібрати зараз + показати статистику")
    choice = input("Вибір [1/2/3]: ").strip()

    if choice == "2":
        make_report()
        return

    if choice == "3":
        collect_once()
        make_report()
        return

    run_loop()


def main():
    args = set(sys.argv[1:])

    if "--once" in args:
        collect_once(verbose="--quiet" not in args)
        if "--report" in args:
            make_report()
        return

    if "--report" in args:
        make_report()
        return

    if "--loop" in args:
        run_loop()
        return

    interactive_main()


if __name__ == "__main__":
    main()
