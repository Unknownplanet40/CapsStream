# -*- coding: utf-8 -*-
"""
routes/__init__.py — Blueprint registration and rate-limit decoration.

Rate limit rules:
  - Auth / PIN endpoints        : 5/minute
  - Scan                        : 1/minute
  - Search                      : 30/minute
  - Streaming endpoints         : unlimited (exempt)
  - All other endpoints         : 60/minute (default set on limiter)
"""

from flask import Flask
from flask_limiter import Limiter


def register_blueprints(app: Flask, limiter: Limiter) -> None:
    """Import and register every Blueprint, then apply per-route rate limits."""

    from routes.profiles import profiles_bp
    from routes.media import media_bp
    from routes.streaming import streaming_bp
    from routes.library import library_bp
    from routes.social import social_bp
    from routes.admin import admin_bp

    # ── Register Blueprints ─────────────────────────────────────────────────
    app.register_blueprint(profiles_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(streaming_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(admin_bp)

    # ── Auth / PIN — 5 per minute ───────────────────────────────────────────
    for view_func_name in [
        "profiles.api_auth_profile",
        "profiles.api_verify_admin_pin",
    ]:
        limiter.limit("5 per minute")(app.view_functions[view_func_name])

    # ── Scan — 1 per minute ─────────────────────────────────────────────────
    limiter.limit("1 per minute")(app.view_functions["admin.api_scan"])

    # ── Search — 30 per minute ──────────────────────────────────────────────
    limiter.limit("30 per minute")(app.view_functions["media.api_search"])

    # ── Streaming & High-Frequency endpoints — Unlimited (exempt) ─────────
    exempt_views = [
        "streaming.api_stream",
        "streaming.api_stream_start",
        "streaming.api_transcode_caps",
        "streaming.api_subtitles",
        "streaming.api_embedded_subtitles",
        "streaming.api_media_thumbnails",
        "streaming.api_media_thumbnail_sheet",
        "profiles.api_profile_heartbeat",
        "social.api_unlock_custom_achievement",
    ]
    for view_name in exempt_views:
        if view_name in app.view_functions:
            limiter.exempt(app.view_functions[view_name])
