# -*- coding: utf-8 -*-
import os
import json
import sqlite3
from datetime import datetime, timedelta
from .connection import get_conn
from .achievements import get_profile_achievements
from .media import enrich_mounted_list, format_file_size_bytes



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
    tech_rows = conn.execute("""
        SELECT file_size, duration FROM media
    """).fetchall()

    total_storage_bytes = sum((r["file_size"] or 0) for r in tech_rows)
    total_storage_formatted = format_file_size_bytes(total_storage_bytes) or "0 GB"
    total_storage_gb = round(total_storage_bytes / (1024 * 1024 * 1024), 2)

    res_counts = {"4K": 0, "1080p": 0, "720p": 0, "SD": 0}
    for r in tech_rows:
        sz = r["file_size"] or 0
        if sz >= 3.5 * 1024 * 1024 * 1024:
            res_counts["4K"] += 1
        elif sz >= 1.2 * 1024 * 1024 * 1024:
            res_counts["1080p"] += 1
        elif sz >= 400 * 1024 * 1024:
            res_counts["720p"] += 1
        elif sz > 0:
            res_counts["SD"] += 1

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
        title = item.get("title", "")

        if m_type in ("series", "anime") and tmdb_id:
            group_key = f"{m_type}_{tmdb_id}"
        elif m_type in ("series", "anime") and title:
            group_key = f"{m_type}_{title.lower()}"
        else:
            group_key = f"movie_{item.get('id')}"

        if group_key not in seen_groups:
            seen_groups.add(group_key)
            if m_type in ("series", "anime"):
                ep_cnt = sum(
                    1 for r in all_history 
                    if r["type"] == m_type and (
                        (tmdb_id and r["tmdb_id"] == tmdb_id) or 
                        (not tmdb_id and (r["title"] or "").lower() == title.lower())
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


# ─── Favorites Queries ────────────────────────────────────────────────────────

