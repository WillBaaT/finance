"""
Garmin health data fetcher and analyzer.
Tracks sleep, activities, heart rate, and HRV.

Usage:
  python garmin_health.py --days 7
  python garmin_health.py --days 30 --output report.json
"""

import os
import json
import argparse
from datetime import date, timedelta
from getpass import getpass

from garminconnect import Garmin


def login(email: str, password: str) -> Garmin:
    token_file = ".garmin_tokens.json"
    client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)

    if os.path.exists(token_file):
        with open(token_file) as f:
            tokens = json.load(f)
        client.login(tokens)
    else:
        client.login()
        with open(token_file, "w") as f:
            json.dump(client.garth.dumps(), f)

    return client


def _prompt_mfa():
    return input("Garmin MFA 驗證碼: ")


def fetch_sleep(client: Garmin, start: date, end: date) -> list[dict]:
    records = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        try:
            data = client.get_sleep_data(day_str)
            daily = data.get("dailySleepDTO", {})
            records.append({
                "date": day_str,
                "total_sleep_seconds": daily.get("sleepTimeSeconds"),
                "deep_sleep_seconds": daily.get("deepSleepSeconds"),
                "light_sleep_seconds": daily.get("lightSleepSeconds"),
                "rem_sleep_seconds": daily.get("remSleepSeconds"),
                "awake_seconds": daily.get("awakeSleepSeconds"),
                "sleep_score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
            })
        except Exception as e:
            records.append({"date": day_str, "error": str(e)})
        current += timedelta(days=1)
    return records


def fetch_activities(client: Garmin, days: int) -> list[dict]:
    raw = client.get_activities(0, days)
    results = []
    for act in raw:
        results.append({
            "date": act.get("startTimeLocal", "")[:10],
            "name": act.get("activityName"),
            "type": act.get("activityType", {}).get("typeKey"),
            "duration_seconds": act.get("duration"),
            "distance_meters": act.get("distance"),
            "calories": act.get("calories"),
            "avg_hr": act.get("averageHR"),
            "max_hr": act.get("maxHR"),
            "avg_pace_per_km": act.get("averageSpeed"),
            "training_effect": act.get("aerobicTrainingEffect"),
        })
    return results


def fetch_hrv(client: Garmin, start: date, end: date) -> list[dict]:
    records = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        try:
            data = client.get_hrv_data(day_str)
            summary = data.get("hrvSummary", {})
            records.append({
                "date": day_str,
                "hrv_weekly_avg": summary.get("weeklyAvg"),
                "hrv_last_night": summary.get("lastNight"),
                "hrv_last_night_5min_high": summary.get("lastNight5MinHigh"),
                "hrv_status": summary.get("status"),
            })
        except Exception as e:
            records.append({"date": day_str, "error": str(e)})
        current += timedelta(days=1)
    return records


def fetch_daily_stats(client: Garmin, start: date, end: date) -> list[dict]:
    records = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        try:
            data = client.get_stats(day_str)
            records.append({
                "date": day_str,
                "steps": data.get("totalSteps"),
                "resting_hr": data.get("restingHeartRate"),
                "avg_stress": data.get("averageStressLevel"),
                "body_battery_high": data.get("maxStressLevel"),  # reused field
                "calories_active": data.get("activeKilocalories"),
                "calories_total": data.get("totalKilocalories"),
                "intensity_minutes": data.get("moderateIntensityMinutes", 0)
                    + data.get("vigorousIntensityMinutes", 0),
            })
        except Exception as e:
            records.append({"date": day_str, "error": str(e)})
        current += timedelta(days=1)
    return records


def summarize(data: dict) -> None:
    print("\n" + "=" * 50)
    print("Garmin 健康資料摘要")
    print("=" * 50)

    sleep = [s for s in data["sleep"] if "error" not in s and s.get("total_sleep_seconds")]
    if sleep:
        avg_sleep_hr = sum(s["total_sleep_seconds"] for s in sleep) / len(sleep) / 3600
        avg_score = sum(s["sleep_score"] for s in sleep if s.get("sleep_score")) / max(
            1, sum(1 for s in sleep if s.get("sleep_score"))
        )
        print(f"\n[睡眠] 平均睡眠時間: {avg_sleep_hr:.1f} 小時 | 平均睡眠分數: {avg_score:.0f}")

    hrv = [h for h in data["hrv"] if "error" not in h and h.get("hrv_last_night")]
    if hrv:
        avg_hrv = sum(h["hrv_last_night"] for h in hrv) / len(hrv)
        print(f"[HRV]  平均夜間 HRV: {avg_hrv:.0f} ms")

    stats = [s for s in data["daily_stats"] if "error" not in s and s.get("steps")]
    if stats:
        avg_steps = sum(s["steps"] for s in stats) / len(stats)
        avg_rhr = sum(s["resting_hr"] for s in stats if s.get("resting_hr")) / max(
            1, sum(1 for s in stats if s.get("resting_hr"))
        )
        print(f"[活動] 平均步數: {avg_steps:,.0f} | 平均靜止心率: {avg_rhr:.0f} bpm")

    acts = data["activities"]
    if acts:
        print(f"\n[運動] 期間共 {len(acts)} 次活動")
        by_type: dict[str, int] = {}
        for a in acts:
            t = a.get("type") or "unknown"
            by_type[t] = by_type.get(t, 0) + 1
        for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"       {t}: {count} 次")

    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Garmin 健康資料分析")
    parser.add_argument("--days", type=int, default=7, help="分析天數 (預設 7)")
    parser.add_argument("--output", default="garmin_data.json", help="輸出檔案名稱")
    args = parser.parse_args()

    email = os.environ.get("GARMIN_EMAIL") or input("Garmin Email: ")
    password = os.environ.get("GARMIN_PASSWORD") or getpass("Garmin 密碼: ")

    print(f"\n正在登入 Garmin Connect...")
    client = login(email, password)
    print("登入成功！\n")

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days - 1)
    print(f"抓取 {start_date} 到 {end_date} 的資料（{args.days} 天）...")

    data = {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "sleep": fetch_sleep(client, start_date, end_date),
        "hrv": fetch_hrv(client, start_date, end_date),
        "daily_stats": fetch_daily_stats(client, start_date, end_date),
        "activities": fetch_activities(client, args.days),
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"資料已儲存至 {args.output}")

    summarize(data)


if __name__ == "__main__":
    main()
