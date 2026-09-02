# -*- coding: utf-8 -*-
import os
import json
import random
import sqlite3
from datetime import datetime, timedelta
from .connection import get_conn
from .achievements import get_profile_achievements
from .media import enrich_mounted_list, format_file_size_bytes, is_item_mounted



def get_profile_watch_stats(profile_id):
    conn = get_conn()
    from datetime import datetime, timedelta

    # 1. Total seconds watched & total items tracked
    total_row = conn.execute("""
        SELECT SUM(position) as total_seconds, COUNT(*) as total_items, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as completed_items
        FROM watch_progress
        WHERE profile_id=?
    """, (profile_id,)).fetchone()

    total_seconds = total_row["total_seconds"] or 0
    total_items = total_row["total_items"] or 0
    completed_items = total_row["completed_items"] or 0
    completion_rate = round((completed_items / total_items * 100), 1) if total_items > 0 else 0
    avg_session_minutes = round((total_seconds / max(1, total_items)) / 60, 1)

    # 2. Peak Viewing Hour
    peak_row = conn.execute("""
        SELECT strftime('%H', updated_at) as hr, COUNT(*) as cnt
        FROM watch_progress
        WHERE profile_id=? AND updated_at IS NOT NULL
        GROUP BY hr ORDER BY cnt DESC LIMIT 1
    """, (profile_id,)).fetchone()

    peak_hour_str = "N/A"
    if peak_row and peak_row["hr"] is not None:
        try:
            h = int(peak_row["hr"])
            h_next = (h + 1) % 24
            ampm1 = "AM" if h < 12 else "PM"
            ampm2 = "AM" if h_next < 12 else "PM"
            display_h1 = h if h <= 12 else h - 12
            if display_h1 == 0: display_h1 = 12
            display_h2 = h_next if h_next <= 12 else h_next - 12
            if display_h2 == 0: display_h2 = 12
            peak_hour_str = f"{display_h1} {ampm1} - {display_h2} {ampm2}"
        except Exception:
            peak_hour_str = "Evening"

    # 3. 7-Day Watch Activity Bar Chart
    now_dt = datetime.now()
    days_data = []
    for i in range(6, -1, -1):
        dt_day = now_dt - timedelta(days=i)
        day_str = dt_day.strftime("%Y-%m-%d")
        day_name = dt_day.strftime("%a")
        
        row_day = conn.execute("""
            SELECT SUM(position) as sec FROM watch_progress
            WHERE profile_id=? AND date(updated_at)=?
        """, (profile_id, day_str)).fetchone()
        sec = row_day["sec"] or 0
        days_data.append({
            "day": day_name,
            "date": day_str,
            "minutes": round(sec / 60, 1)
        })

    # 4. Type breakdown (movies vs series vs anime)
    type_rows = conn.execute("""
        SELECT m.type, COUNT(*) as cnt, SUM(wp.position) as seconds
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=?
        GROUP BY m.type
    """, (profile_id,)).fetchall()

    type_breakdown = {r["type"]: {"count": r["cnt"], "seconds": r["seconds"] or 0} for r in type_rows}

    # 5. Genre breakdown (aggregate genres from media)
    media_genres = conn.execute("""
        SELECT m.genres, wp.position
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.genres IS NOT NULL AND m.genres != ''
    """, (profile_id,)).fetchall()

    genre_counts = {}
    for r in media_genres:
        g_list = [g.strip() for g in r["genres"].split(",") if g.strip()]
        for g in g_list:
            genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted([{"genre": g, "count": c} for g, c in genre_counts.items()], key=lambda x: x["count"], reverse=True)[:6]

    # 6. Technical Stats & Resolution/Storage
    media_rows = conn.execute("""
        SELECT file_path, file_size, duration, type FROM media
    """).fetchall()
    mounted_media_rows = []
    for r in media_rows:
        row = dict(r)
        file_path = row.get("file_path")
        if file_path and is_item_mounted({"file_path": file_path}):
            mounted_media_rows.append(row)

    total_storage_bytes = sum((r["file_size"] or 0) for r in mounted_media_rows)
    total_storage_formatted = format_file_size_bytes(total_storage_bytes) or "0 GB"
    total_storage_gb = round(total_storage_bytes / (1024 * 1024 * 1024), 2)

    from backend.db.media import get_media_resolution
    RESOLUTION_HIERARCHY = ["8K", "4K", "1440p", "1080p", "720p", "SD"]
    dynamic_counts = {}

    for r in mounted_media_rows:
        res = get_media_resolution(r)
        if res:
            dynamic_counts[res] = dynamic_counts.get(res, 0) + 1

    # Ensure standard baseline tiers are always present for UI stability
    for std_res in ["4K", "1080p", "720p", "SD"]:
        if std_res not in dynamic_counts:
            dynamic_counts[std_res] = 0

    # Sort keys by resolution hierarchy (highest first)
    res_counts = {}
    for k in sorted(
        dynamic_counts.keys(),
        key=lambda x: RESOLUTION_HIERARCHY.index(x) if x in RESOLUTION_HIERARCHY else 99
    ):
        res_counts[k] = dynamic_counts[k]

    # 7. Recent history (Consolidated 10 distinct titles watched)
    all_history = conn.execute("""
        SELECT m.*, wp.position, wp.duration, wp.completed, wp.updated_at as last_watched
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=?
        ORDER BY wp.updated_at DESC
    """, (profile_id,)).fetchall()

    grouped_history = []
    seen_groups = set()

    for row in all_history:
        item = dict(row)
        m_type = item.get("type", "movie")
        tmdb_id = item.get("tmdb_id")
        title = (item.get("title") or "").strip()

        if tmdb_id is not None:
            group_key = f"{m_type}_{tmdb_id}"
        elif title:
            group_key = f"{m_type}_{title.lower()}"
        else:
            group_key = f"{m_type}_{item.get('id')}"

        if group_key not in seen_groups:
            seen_groups.add(group_key)
            if m_type in ("series", "anime"):
                ep_cnt = sum(
                    1 for r in all_history
                    if r["type"] == m_type and (
                        (tmdb_id is not None and r["tmdb_id"] == tmdb_id) or
                        (tmdb_id is None and (r["title"] or "").strip().lower() == title.lower())
                    )
                )
                item["ep_count"] = ep_cnt
            else:
                item["ep_count"] = 1
            grouped_history.append(item)
            if len(grouped_history) >= 10:
                break

    history_rows = grouped_history
    conn.close()

    achievements = get_profile_achievements(profile_id)

    return {
        "total_seconds": total_seconds,
        "total_items": total_items,
        "completed_items": completed_items,
        "completion_rate": completion_rate,
        "avg_session_minutes": avg_session_minutes,
        "peak_hour": peak_hour_str,
        "weekly_activity": days_data,
        "type_breakdown": type_breakdown,
        "top_genres": top_genres,
        "technical_stats": {
            "total_storage_gb": total_storage_gb,
            "total_storage_formatted": total_storage_formatted,
            "resolutions": res_counts
        },
        "recent_history": enrich_mounted_list([dict(r) for r in history_rows]),
        "achievements": achievements
    }


def get_profile_wrapped_analytics(profile_id, period="year", year=None):
    """
    Compute comprehensive CapsStream Wrapped & Advanced Analytics for a profile.
    Supports period in ('year', 'month', 'all').
    """
    conn = get_conn()
    now_dt = datetime.now()

    # Available years list for UI selector
    available_years_rows = conn.execute("""
        SELECT DISTINCT strftime('%Y', updated_at) as yr
        FROM watch_progress
        WHERE profile_id=? AND updated_at IS NOT NULL
        ORDER BY yr DESC
    """, (profile_id,)).fetchall()

    years_set = {str(now_dt.year)}
    for r in available_years_rows:
        if r["yr"]:
            years_set.add(str(r["yr"]))
    available_years = sorted(list(years_set), reverse=True)

    # Determine date filters
    target_year = now_dt.year
    if period == "year":
        if year:
            try:
                target_year = int(year)
            except (ValueError, TypeError):
                target_year = now_dt.year
        start_date = f"{target_year:04d}-01-01 00:00:00"
        end_date = f"{target_year:04d}-12-31 23:59:59"
        date_filter = "AND wp.updated_at >= ? AND wp.updated_at <= ?"
        date_params = [start_date, end_date]
        label = f"{target_year}"
    elif period == "month":
        start_date = (now_dt - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
        date_filter = "AND wp.updated_at >= ?"
        date_params = [start_date]
        label = "Last 30 Days"
    else:
        period = "all"
        date_filter = ""
        date_params = []
        label = "All Time"

    # 1. Base query for all matching watch progress + media
    base_query = f"""
        SELECT wp.media_id, wp.position, wp.duration as wp_duration, wp.completed, wp.updated_at,
               m.id as m_id, m.type as m_type, m.title, m.original_title, m.year as m_year,
               m.season, m.episode, m.ep_title, m.duration as m_duration, m.genres,
               m.rating, m.poster_path, m.backdrop_path, m.file_path, m.file_size,
               m.cast_json, m.tmdb_id
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? {date_filter}
        ORDER BY wp.updated_at DESC
    """
    rows = conn.execute(base_query, [profile_id] + date_params).fetchall()

    total_seconds = sum((r["position"] or 0) for r in rows)
    total_items = len(rows)
    completed_items = sum(1 for r in rows if r["completed"])
    completion_rate = round((completed_items / total_items * 100), 1) if total_items > 0 else 0
    total_hours = round(total_seconds / 3600, 1)
    avg_session_minutes = round((total_seconds / max(1, total_items)) / 60, 1)

    # 2. Activity Heatmap & Streaks
    day_map_query = f"""
        SELECT date(wp.updated_at) as day_str,
               SUM(wp.position) as day_seconds,
               COUNT(*) as day_items
        FROM watch_progress wp
        WHERE wp.profile_id=? {date_filter} AND wp.updated_at IS NOT NULL
        GROUP BY day_str
        ORDER BY day_str ASC
    """
    day_rows = conn.execute(day_map_query, [profile_id] + date_params).fetchall()
    day_dict = {r["day_str"]: {"seconds": r["day_seconds"] or 0, "count": r["day_items"] or 0} for r in day_rows}

    # Populate complete calendar for heatmap with Monday-aligned columns
    if period == "year":
        start_d = datetime(target_year, 1, 1)
        end_d = datetime(target_year, 12, 31)
    elif period == "month":
        end_d = now_dt
        start_d = now_dt - timedelta(days=29)
    else:  # all: rolling 52 weeks (365 days) ending today
        end_d = now_dt
        start_d = now_dt - timedelta(days=364)

    # Pad so start_d aligns to Monday (0=Mon, 6=Sun)
    leading_pad = start_d.weekday()
    first_mon = start_d - timedelta(days=leading_pad)

    # Pad so end_d aligns to Sunday (6=Sun)
    trailing_pad = 6 - end_d.weekday()
    last_sun = end_d + timedelta(days=trailing_pad)

    calendar_days = []
    cur_d = first_mon
    today_date = now_dt.date()

    while cur_d <= last_sun:
        is_padding = cur_d < start_d or cur_d > end_d
        d_str = cur_d.strftime("%Y-%m-%d")
        data = day_dict.get(d_str, {"seconds": 0, "count": 0}) if not is_padding else {"seconds": 0, "count": 0}
        mins = round(data["seconds"] / 60, 1)
        if mins == 0: intensity = 0
        elif mins <= 30: intensity = 1
        elif mins <= 90: intensity = 2
        elif mins <= 180: intensity = 3
        else: intensity = 4

        is_future = False
        if not is_padding:
            if period == "year":
                is_future = cur_d.date() > today_date if target_year == now_dt.year else False
            else:
                is_future = cur_d.date() > today_date

        calendar_days.append({
            "date": "" if is_padding else d_str,
            "day_of_week": cur_d.weekday(),
            "minutes": mins,
            "count": data["count"],
            "intensity": 0 if is_padding else intensity,
            "is_future": is_future,
            "is_padding": is_padding
        })
        cur_d += timedelta(days=1)

    total_cells = len(calendar_days)
    num_weeks = total_cells // 7

    # Generate month labels aligned with week columns
    month_labels = []
    prev_m = None
    for w in range(num_weeks):
        mid_day = first_mon + timedelta(days=w * 7 + 3)
        cur_m = mid_day.strftime("%b")
        if cur_m != prev_m:
            month_labels.append(cur_m)
            prev_m = cur_m
        else:
            month_labels.append("")

    # Streaks calculation across active dates in this period
    period_active_dates = sorted([
        datetime.strptime(d["date"], "%Y-%m-%d").date()
        for d in calendar_days
        if not d["is_padding"] and d["minutes"] > 0 and d["date"]
    ])

    longest_streak = 0
    temp_streak = 0
    prev_d = None
    for d in period_active_dates:
        if prev_d is None or (d - prev_d).days == 1:
            temp_streak += 1
        else:
            temp_streak = 1
        if temp_streak > longest_streak:
            longest_streak = temp_streak
        prev_d = d

    # Also compute all-time active dates for all-time streak & total active days
    all_active_days_rows = conn.execute("""
        SELECT DISTINCT date(updated_at) as day_str
        FROM watch_progress
        WHERE profile_id=? AND position >= 60 AND updated_at IS NOT NULL
        ORDER BY day_str ASC
    """, (profile_id,)).fetchall()

    all_active_dates = set()
    all_active_list = []
    for r in all_active_days_rows:
        if r["day_str"]:
            try:
                d_obj = datetime.strptime(r["day_str"], "%Y-%m-%d").date()
                all_active_dates.add(d_obj)
                all_active_list.append(d_obj)
            except Exception:
                pass

    if period == "all":
        all_longest_streak = 0
        t_streak = 0
        p_d = None
        for d in sorted(all_active_list):
            if p_d is None or (d - p_d).days == 1:
                t_streak += 1
            else:
                t_streak = 1
            if t_streak > all_longest_streak:
                all_longest_streak = t_streak
            p_d = d
        longest_streak = all_longest_streak

    today = now_dt.date()
    current_streak = 0
    check_d = today if today in all_active_dates else today - timedelta(days=1)
    if check_d in all_active_dates:
        while check_d in all_active_dates:
            current_streak += 1
            check_d -= timedelta(days=1)

    days_active = len(all_active_dates) if period == "all" else len(period_active_dates)

    # 3. Binge Records & Marathon Stats
    biggest_binge_day = None
    max_day_seconds = 0
    for d_str, d_info in day_dict.items():
        if d_info["seconds"] > max_day_seconds:
            max_day_seconds = d_info["seconds"]
            biggest_binge_day = {
                "date": d_str,
                "minutes": round(d_info["seconds"] / 60, 1),
                "hours": round(d_info["seconds"] / 3600, 1),
                "items_count": d_info["count"]
            }

    ep_day_rows = conn.execute(f"""
        SELECT date(wp.updated_at) as day_str, COUNT(*) as ep_count
        FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type IN ('series', 'anime') {date_filter}
        GROUP BY day_str
        ORDER BY ep_count DESC LIMIT 1
    """, [profile_id] + date_params).fetchone()
    most_episodes_in_day = ep_day_rows["ep_count"] if ep_day_rows else 0

    # 4. Hourly Viewing Matrix & Day-of-Week
    hourly_rows = conn.execute(f"""
        SELECT strftime('%H', wp.updated_at) as hr, SUM(wp.position) as sec, COUNT(*) as cnt
        FROM watch_progress wp
        WHERE wp.profile_id=? {date_filter} AND wp.updated_at IS NOT NULL
        GROUP BY hr
    """, [profile_id] + date_params).fetchall()

    hourly_dict = {int(r["hr"]): {"seconds": r["sec"] or 0, "count": r["cnt"] or 0} for r in hourly_rows if r["hr"] is not None}
    hourly_distribution = []
    for h in range(24):
        h_data = hourly_dict.get(h, {"seconds": 0, "count": 0})
        display_h = h if h <= 12 else h - 12
        if display_h == 0: display_h = 12
        ampm = "AM" if h < 12 else "PM"
        hourly_distribution.append({
            "hour": h,
            "label": f"{display_h} {ampm}",
            "seconds": h_data["seconds"],
            "minutes": round(h_data["seconds"] / 60, 1),
            "count": h_data["count"]
        })

    morning_sec = sum(hourly_dict.get(h, {}).get("seconds", 0) for h in range(6, 12))
    afternoon_sec = sum(hourly_dict.get(h, {}).get("seconds", 0) for h in range(12, 18))
    evening_sec = sum(hourly_dict.get(h, {}).get("seconds", 0) for h in range(18, 24))
    late_night_sec = sum(hourly_dict.get(h, {}).get("seconds", 0) for h in range(0, 6))

    dow_rows = conn.execute(f"""
        SELECT strftime('%w', wp.updated_at) as dow, SUM(wp.position) as sec, COUNT(*) as cnt
        FROM watch_progress wp
        WHERE wp.profile_id=? {date_filter} AND wp.updated_at IS NOT NULL
        GROUP BY dow
    """, [profile_id] + date_params).fetchall()
    dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    dow_dict = {int(r["dow"]): {"seconds": r["sec"] or 0, "count": r["cnt"] or 0} for r in dow_rows if r["dow"] is not None}
    dow_distribution = []
    weekday_sec = 0
    weekend_sec = 0
    for idx, name in enumerate(dow_names):
        d_data = dow_dict.get(idx, {"seconds": 0, "count": 0})
        dow_distribution.append({
            "dow": idx,
            "name": name,
            "seconds": d_data["seconds"],
            "minutes": round(d_data["seconds"] / 60, 1),
            "count": d_data["count"]
        })
        if idx in (0, 6):
            weekend_sec += d_data["seconds"]
        else:
            weekday_sec += d_data["seconds"]

    total_dow_sec = max(1, weekday_sec + weekend_sec)
    weekday_pct = round((weekday_sec / total_dow_sec) * 100, 1)
    weekend_pct = round((weekend_sec / total_dow_sec) * 100, 1)

    # 5. Type Breakdown
    type_counts = {"movie": {"count": 0, "seconds": 0, "hours": 0}, "series": {"count": 0, "seconds": 0, "hours": 0}, "anime": {"count": 0, "seconds": 0, "hours": 0}}
    for r in rows:
        mtype = r["m_type"]
        if mtype in type_counts:
            type_counts[mtype]["count"] += 1
            type_counts[mtype]["seconds"] += (r["position"] or 0)
    for k in type_counts:
        type_counts[k]["hours"] = round(type_counts[k]["seconds"] / 3600, 1)

    # 6. Top Genres with Colors & %
    genre_accents = ["#ef4444", "#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#06b6d4", "#f97316"]
    genre_totals = {}
    for r in rows:
        g_raw = r["genres"]
        pos = r["position"] or 0
        if g_raw:
            g_list = [g.strip() for g in g_raw.split(",") if g.strip()]
            for g in g_list:
                if g not in genre_totals:
                    genre_totals[g] = {"count": 0, "seconds": 0}
                genre_totals[g]["count"] += 1
                genre_totals[g]["seconds"] += pos

    total_genre_sec = sum(g["seconds"] for g in genre_totals.values()) or 1
    sorted_genres = sorted(
        [{"genre": g, "count": v["count"], "seconds": v["seconds"], "hours": round(v["seconds"] / 3600, 1),
          "percent": round((v["seconds"] / total_genre_sec) * 100, 1)}
         for g, v in genre_totals.items()],
        key=lambda x: x["seconds"],
        reverse=True
    )
    for i, g in enumerate(sorted_genres[:8]):
        g["color"] = genre_accents[i % len(genre_accents)]
    top_genres = sorted_genres[:8]

    # 7. Top Movies & Top Series / Anime
    movie_items = {}
    show_items = {}
    for r in rows:
        mtype = r["m_type"]
        tmdb_id = r["tmdb_id"]
        title = r["title"] or "Untitled"
        poster = r["poster_path"]
        pos = r["position"] or 0
        if mtype == "movie":
            key = tmdb_id or title
            if key not in movie_items:
                movie_items[key] = {
                    "id": r["m_id"],
                    "tmdb_id": tmdb_id,
                    "title": title,
                    "year": r["m_year"],
                    "poster_path": poster,
                    "backdrop_path": r["backdrop_path"],
                    "rating": r["rating"],
                    "seconds": 0,
                    "completed": bool(r["completed"])
                }
            movie_items[key]["seconds"] += pos
            if r["completed"]:
                movie_items[key]["completed"] = True
        else:
            key = tmdb_id or title
            if key not in show_items:
                show_items[key] = {
                    "id": r["m_id"],
                    "tmdb_id": tmdb_id,
                    "type": mtype,
                    "title": title,
                    "year": r["m_year"],
                    "poster_path": poster,
                    "backdrop_path": r["backdrop_path"],
                    "rating": r["rating"],
                    "episodes_watched": 0,
                    "seconds": 0
                }
            show_items[key]["episodes_watched"] += 1
            show_items[key]["seconds"] += pos

    top_movies = sorted(
        [dict(v, hours=round(v["seconds"] / 3600, 1)) for v in movie_items.values()],
        key=lambda x: x["seconds"],
        reverse=True
    )[:5]

    top_shows = sorted(
        [dict(v, hours=round(v["seconds"] / 3600, 1)) for v in show_items.values()],
        key=lambda x: (x["episodes_watched"], x["seconds"]),
        reverse=True
    )[:5]

    # 8. Top Cast & Talent
    actor_map = {}
    for r in rows:
        cast_raw = r["cast_json"]
        if not cast_raw:
            continue
        try:
            cast_list = json.loads(cast_raw) if isinstance(cast_raw, str) else cast_raw
            if isinstance(cast_list, list):
                for actor in cast_list[:8]:
                    a_name = actor.get("name")
                    if not a_name:
                        continue
                    p_path = actor.get("profile") or actor.get("profile_path") or actor.get("avatar")
                    if a_name not in actor_map:
                        actor_map[a_name] = {
                            "name": a_name,
                            "character": actor.get("character") or "",
                            "profile_path": p_path,
                            "titles_count": 0,
                            "titles": set()
                        }
                    else:
                        if not actor_map[a_name]["profile_path"] and p_path:
                            actor_map[a_name]["profile_path"] = p_path
                        if not actor_map[a_name]["character"] and actor.get("character"):
                            actor_map[a_name]["character"] = actor.get("character")
                    actor_map[a_name]["titles_count"] += 1
                    actor_map[a_name]["titles"].add(r["title"] or "")
        except Exception:
            pass

    top_actors = sorted(
        [{"name": k, "character": v["character"], "profile_path": v["profile_path"],
          "titles_count": v["titles_count"], "sample_titles": list(v["titles"])[:2]}
         for k, v in actor_map.items()],
        key=lambda x: x["titles_count"],
        reverse=True
    )[:8]

    # 9. Quality & Resolutions
    from backend.db.media import get_media_resolution
    res_counts = {}
    for r in rows:
        res = get_media_resolution(dict(r)) or "1080p"
        res_counts[res] = res_counts.get(res, 0) + 1

    # 10. Viewer Archetype Engine
    anime_sec = type_counts["anime"]["seconds"]
    k4_count = res_counts.get("4K", 0) + res_counts.get("8K", 0)
    k4_ratio = (k4_count / max(1, total_items))
    late_night_ratio = (late_night_sec / max(1, total_seconds))
    weekend_ratio = (weekend_sec / max(1, total_seconds))
    anime_ratio = (anime_sec / max(1, total_seconds))
    top_genre_ratio = (top_genres[0]["percent"] / 100.0) if top_genres else 0

    if late_night_ratio >= 0.35 and late_night_sec >= 1800:
        archetype = {
            "id": "midnight_binge_lord",
            "title": "Midnight Binge Lord",
            "tagline": "Sleep is merely a suggestion. The night belongs to the next episode.",
            "badge": "ph-moon-stars",
            "color": "#8b5cf6",
            "description": "Your prime viewing hours kick in when the rest of the world is asleep."
        }
    elif anime_ratio >= 0.40:
        archetype = {
            "id": "anime_ascendant",
            "title": "Anime Ascendant",
            "tagline": "Powered by ramen, Japanese subtitles, and unmatched shonen willpower.",
            "badge": "ph-sword",
            "color": "#f43f5e",
            "description": "You dive deep into anime universes, from seasonal epics to classic arcs."
        }
    elif weekend_ratio >= 0.60:
        archetype = {
            "id": "weekend_marathoner",
            "title": "The Weekend Marathoner",
            "tagline": "Work hard during the week, stream without limits on Saturday & Sunday.",
            "badge": "ph-couch",
            "color": "#06b6d4",
            "description": "Your weekends are dedicated cinema marathons and binge sessions."
        }
    elif k4_ratio >= 0.40:
        archetype = {
            "id": "4k_cinematic_purist",
            "title": "4K Cinematic Purist",
            "tagline": "Every pixel matters. Uncompromising devotion to cinema-grade visuals.",
            "badge": "ph-projector-screen",
            "color": "#eab308",
            "description": "Only ultra-crisp resolutions and pristine bitrates make it to your screen."
        }
    elif completion_rate >= 80 and completed_items >= 4:
        archetype = {
            "id": "the_completionist",
            "title": "The Completionist",
            "tagline": "No credits skipped. No unfinished business. Pure cinematic dedication.",
            "badge": "ph-seal-check",
            "color": "#10b981",
            "description": "When you start a movie or season, you see it through to the final credits."
        }
    elif top_genre_ratio >= 0.45 and len(top_genres) > 0:
        tg = top_genres[0]["genre"]
        archetype = {
            "id": "genre_connoisseur",
            "title": f"{tg} Connoisseur",
            "tagline": f"A true master of {tg.lower()} cinema with refined and unwavering taste.",
            "badge": "ph-crown",
            "color": "#ec4899",
            "description": f"You know the {tg.lower()} genre inside out and follow its greatest stories."
        }
    else:
        archetype = {
            "id": "omnivorous_cinephile",
            "title": "The Omnivorous Cinephile",
            "tagline": "An eclectic taste across genres, formats, and worlds. A true film lover.",
            "badge": "ph-film-strip",
            "color": "#3b82f6",
            "description": "You appreciate great cinema in all forms, hopping seamlessly across diverse genres."
        }

    # 11. Top Obsession (#1 Title)
    all_titles = []
    for k, v in movie_items.items():
        all_titles.append({
            "title": v["title"],
            "type": "movie",
            "poster_path": v["poster_path"],
            "backdrop_path": v["backdrop_path"],
            "year": v.get("year"),
            "seconds": v["seconds"],
            "hours": round(v["seconds"] / 3600, 1),
            "minutes": round(v["seconds"] / 60),
            "plays": 1,
            "badge": "Cinema Favorite" if v.get("completed") else "Top Film"
        })
    for k, v in show_items.items():
        all_titles.append({
            "title": v["title"],
            "type": v.get("type", "series"),
            "poster_path": v["poster_path"],
            "backdrop_path": v["backdrop_path"],
            "year": v.get("year"),
            "seconds": v["seconds"],
            "hours": round(v["seconds"] / 3600, 1),
            "minutes": round(v["seconds"] / 60),
            "plays": v["episodes_watched"],
            "badge": "Ultimate Binge" if v["episodes_watched"] >= 5 else "Marathon Favorite"
        })
    all_titles.sort(key=lambda x: x["seconds"], reverse=True)
    top_obsession = all_titles[0] if all_titles else None

    # 12. Audio & Subtitle DNA
    try:
        prof_row = conn.execute("SELECT default_audio_lang, default_sub_lang FROM profiles WHERE id=?", (profile_id,)).fetchone()
        pref_audio = (prof_row["default_audio_lang"] if prof_row and prof_row["default_audio_lang"] else "Auto (Original)")
        pref_sub = (prof_row["default_sub_lang"] if prof_row and prof_row["default_sub_lang"] else "English")
    except Exception:
        pref_audio = "Auto (Original)"
        pref_sub = "English"
    anime_ratio_pct = round((anime_sec / max(1, total_seconds)) * 100, 1)

    if anime_ratio_pct >= 40:
        sub_style = "Original Voice Purist"
        sub_desc = "You prefer authentic Japanese voice acting with translated subtitles."
    elif total_hours >= 10:
        sub_style = "Subtitle Aficionado"
        sub_desc = "Subtitles on, volume crisp. You never miss a single line of dialogue."
    else:
        sub_style = "Effortless Listener"
        sub_desc = "Balanced viewing style, taking in both original dubs and localized tracks."

    audio_sub_dna = {
        "preferred_audio": pref_audio,
        "preferred_subtitle": pref_sub,
        "anime_ratio_pct": anime_ratio_pct,
        "sub_style": sub_style,
        "sub_desc": sub_desc
    }

    # 13. Speed Binge & Fastest Season Completed
    season_groups = {}
    for r in rows:
        if r["m_type"] in ("series", "anime") and r["season"] is not None:
            s_key = (r["title"], r["season"])
            if s_key not in season_groups:
                season_groups[s_key] = {
                    "title": r["title"],
                    "season": r["season"],
                    "poster_path": r["poster_path"],
                    "episodes": [],
                    "updated_ats": []
                }
            season_groups[s_key]["episodes"].append(r["episode"])
            if r["updated_at"]:
                try:
                    dt = datetime.fromisoformat(r["updated_at"].replace("Z", ""))
                    season_groups[s_key]["updated_ats"].append(dt)
                except Exception:
                    pass

    fastest_season = None
    min_season_hours = float("inf")
    for s_info in season_groups.values():
        if len(s_info["episodes"]) >= 3 and len(s_info["updated_ats"]) >= 2:
            s_info["updated_ats"].sort()
            delta_hours = max(0.5, (s_info["updated_ats"][-1] - s_info["updated_ats"][0]).total_seconds() / 3600.0)
            if delta_hours < min_season_hours:
                min_season_hours = delta_hours
                time_label = f"{round(delta_hours, 1)} hours" if delta_hours < 24 else f"{round(delta_hours / 24, 1)} days"
                fastest_season = {
                    "title": s_info["title"],
                    "season": s_info["season"],
                    "poster_path": s_info["poster_path"],
                    "episodes_count": len(s_info["episodes"]),
                    "hours_taken": round(delta_hours, 1),
                    "time_label": time_label
                }

    # 14. Ultra-HD Cinema Specs & Bandwidth
    total_streamed_bytes = 0
    for r in rows:
        fsize = r["file_size"] or 0
        m_dur = r["m_duration"] or r["wp_duration"] or 0
        pos = r["position"] or 0
        if fsize > 0:
            if m_dur > 0:
                fraction = min(1.0, max(0.05, pos / float(m_dur)))
                total_streamed_bytes += int(fsize * fraction)
            else:
                total_streamed_bytes += fsize
        else:
            total_streamed_bytes += int(pos * 500_000)

    total_gb_streamed = round(total_streamed_bytes / (1024 ** 3), 2)
    tech_specs = {
        "resolutions": res_counts,
        "k4_percentage": round(k4_ratio * 100, 1),
        "total_gb_streamed": total_gb_streamed,
        "direct_play_pct": 98.4
    }

    # 15. Interactive Guessing Quizzes
    genre_quiz = None
    if top_genres:
        correct_genre = top_genres[0]["genre"]
        distractors = [g["genre"] for g in top_genres[1:4]]
        fallback_pool = ["Sci-Fi", "Action", "Drama", "Animation", "Comedy", "Thriller", "Horror"]
        for fg in fallback_pool:
            if len(distractors) >= 3:
                break
            if fg != correct_genre and fg not in distractors:
                distractors.append(fg)
        opts = [{"id": f"g_opt_{i}", "text": text, "is_correct": (text == correct_genre)}
                for i, text in enumerate([correct_genre] + distractors[:3])]
        random.shuffle(opts)
        genre_quiz = {
            "question": "Which genre claimed the most hours of your year?",
            "correct_answer": correct_genre,
            "options": opts
        }

    talent_quiz = None
    if top_actors:
        correct_actor = top_actors[0]["name"]
        distractors = [a["name"] for a in top_actors[1:3]]
        fallback_actors = ["Leonardo DiCaprio", "Scarlett Johansson", "Pedro Pascal", "Keanu Reeves"]
        for fa in fallback_actors:
            if len(distractors) >= 2:
                break
            if fa != correct_actor and fa not in distractors:
                distractors.append(fa)
        opts = [{"id": f"t_opt_{i}", "text": text, "is_correct": (text == correct_actor)}
                for i, text in enumerate([correct_actor] + distractors[:2])]
        random.shuffle(opts)
        talent_quiz = {
            "question": "Which talent appeared on your screen the most?",
            "correct_answer": correct_actor,
            "correct_profile": top_actors[0].get("profile_path"),
            "options": opts
        }

    conn.close()

    return {
        "period": period,
        "year": target_year if period == "year" else None,
        "label": label,
        "available_years": available_years,
        "overview": {
            "total_seconds": total_seconds,
            "total_hours": total_hours,
            "total_items": total_items,
            "completed_items": completed_items,
            "completion_rate": completion_rate,
            "avg_session_minutes": avg_session_minutes
        },
        "top_obsession": top_obsession,
        "audio_sub_dna": audio_sub_dna,
        "speed_binge": {
            "fastest_season": fastest_season,
            "longest_streak": longest_streak,
            "current_streak": current_streak,
            "biggest_binge_day": biggest_binge_day,
            "most_episodes_in_day": most_episodes_in_day
        },
        "heatmap": {
            "days": calendar_days,
            "month_labels": month_labels,
            "weeks_count": num_weeks,
            "days_active": days_active,
            "longest_streak": longest_streak,
            "current_streak": current_streak
        },
        "binge_records": {
            "biggest_binge_day": biggest_binge_day,
            "most_episodes_in_day": most_episodes_in_day
        },
        "habits": {
            "hourly": hourly_distribution,
            "day_of_week": dow_distribution,
            "weekday_pct": weekday_pct,
            "weekend_pct": weekend_pct,
            "time_windows": {
                "morning_hours": round(morning_sec / 3600, 1),
                "afternoon_hours": round(afternoon_sec / 3600, 1),
                "evening_hours": round(evening_sec / 3600, 1),
                "late_night_hours": round(late_night_sec / 3600, 1)
            }
        },
        "content_breakdown": {
            "types": type_counts,
            "top_genres": top_genres,
            "top_movies": top_movies,
            "top_shows": top_shows
        },
        "talent": {
            "top_actors": top_actors
        },
        "technical": {
            "resolutions": res_counts
        },
        "tech_specs": tech_specs,
        "quizzes": {
            "genre": genre_quiz,
            "talent": talent_quiz
        },
        "archetype": archetype
    }

