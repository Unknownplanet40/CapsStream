# -*- coding: utf-8 -*-
import os
import json
import time
import sqlite3
from datetime import datetime, timedelta
from .connection import get_conn

ACHIEVEMENTS = [
    {
        "id": "first_watch",
        "title": "First Steps",
        "icon": "ph-film-strip",
        "description": "Watch your first video title in CapsStream",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "marathoner",
        "title": "Marathon Runner",
        "icon": "ph-timer",
        "description": "Accumulate 5 hours of total watch time",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "binge_master",
        "title": "Binge Titan",
        "icon": "ph-trophy",
        "description": "Accumulate 24 hours of total watch time",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "century_watcher",
        "title": "100 Hour Club",
        "icon": "ph-hourglass",
        "description": "Accumulate 100 hours of total watch time",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "cinephile",
        "title": "Cinephile Legend",
        "icon": "ph-popcorn",
        "description": "Complete 5 or more movies or episodes",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "master_completer",
        "title": "Master Completer",
        "icon": "ph-medal",
        "description": "Complete 20 or more titles or episodes",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "titan_completer",
        "title": "Titan Completer",
        "icon": "ph-crown",
        "description": "Complete 50 or more titles or episodes",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "streak_3",
        "title": "3-Day Streak",
        "icon": "ph-fire",
        "description": "Watch media 3 days in a row",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "streak_7",
        "title": "Weekly Streak",
        "icon": "ph-fire-simple",
        "description": "Watch media every day for a full week",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "streak_30",
        "title": "Monthly Legend",
        "icon": "ph-trophy",
        "description": "Watch media 30 days in a row",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "ten_titles",
        "title": "Ten Down",
        "icon": "ph-books",
        "description": "Watch at least 10 different library titles",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "fifty_titles",
        "title": "Library Veteran",
        "icon": "ph-film-slate",
        "description": "Watch at least 50 different library titles",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "hundred_titles",
        "title": "Centurion Streamer",
        "icon": "ph-sparkle",
        "description": "Watch at least 100 different library titles",
        "category": "Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "quick_session",
        "title": "Quick Bite",
        "icon": "ph-lightning",
        "description": "Complete a short watch session (under 15m)",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "long_session",
        "title": "Feature Length",
        "icon": "ph-film-strip",
        "description": "Watch a single session over 2 hours long",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "marathon_session",
        "title": "Mega Marathon",
        "icon": "ph-trophy",
        "description": "Watch a single continuous session over 4 hours long",
        "category": "Milestones",
        "rarity": "Gold"
    },
    {
        "id": "first_finish",
        "title": "Finish Line",
        "icon": "ph-check-circle",
        "description": "Complete your very first movie or show episode",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "halfway_there",
        "title": "Halfway Hero",
        "icon": "ph-medal",
        "description": "Reach 50% completion on a series",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "season_finale",
        "title": "Season Finale",
        "icon": "ph-medal",
        "description": "Watch the final episode of any TV season",
        "category": "Milestones",
        "rarity": "Silver"
    },
    {
        "id": "credits_roll",
        "title": "Roll Credits",
        "icon": "ph-clapperboard",
        "description": "Watch a movie all the way through to 100%",
        "category": "Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "night_owl",
        "title": "Night Owl",
        "icon": "ph-moon",
        "description": "Watch a title late at night (12 AM - 4 AM)",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "early_bird",
        "title": "Early Bird",
        "icon": "ph-sun",
        "description": "Watch a title early in the morning (5 AM - 8 AM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "midnight_marauder",
        "title": "Midnight Marauder",
        "icon": "ph-moon",
        "description": "Start playing video exactly at midnight",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "lunchtime_streamer",
        "title": "Lunch Streamer",
        "icon": "ph-timer",
        "description": "Watch media during lunch hour (12 PM - 2 PM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "primetime_viewer",
        "title": "Prime Time",
        "icon": "ph-timer",
        "description": "Watch media during evening prime time (8 PM - 10 PM)",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "weekend_warrior",
        "title": "Weekend Warrior",
        "icon": "ph-calendar-check",
        "description": "Stream 5 or more titles during Saturday & Sunday",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "monday_blues",
        "title": "Monday Cure",
        "icon": "ph-sun",
        "description": "Watch a movie or episode on a Monday",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "friday_night",
        "title": "Friday Movie Night",
        "icon": "ph-film-strip",
        "description": "Stream a movie on Friday night",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "dawn_patrol",
        "title": "Dawn Patrol",
        "icon": "ph-medal",
        "description": "Watch media right at sunrise",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "afternoon_delight",
        "title": "Afternoon Matinee",
        "icon": "ph-medal",
        "description": "Watch a movie between 2 PM and 5 PM",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "daily_dose",
        "title": "Daily Ritual",
        "icon": "ph-medal",
        "description": "Watch at least one title every day for 5 days",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "binge_session",
        "title": "Binge Session",
        "icon": "ph-medal",
        "description": "Watch 3 consecutive episodes in one sitting",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "triple_threat",
        "title": "Triple Feature",
        "icon": "ph-trophy",
        "description": "Watch 3 full movies in a single day",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "all_nighter",
        "title": "All Nighter",
        "icon": "ph-moon",
        "description": "Stream continuously from 1 AM to 6 AM",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "tea_time",
        "title": "Tea Break",
        "icon": "ph-timer",
        "description": "Watch a short episode during afternoon tea time",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "clockwork",
        "title": "Like Clockwork",
        "icon": "ph-timer",
        "description": "Stream at the exact same hour 3 days in a row",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "holiday_binge",
        "title": "Holiday Binger",
        "icon": "ph-sun",
        "description": "Watch media during a weekend holiday",
        "category": "Viewing Habits",
        "rarity": "Silver"
    },
    {
        "id": "silent_watcher",
        "title": "Silent Watcher",
        "icon": "ph-timer",
        "description": "Watch media late night with muted or low volume",
        "category": "Viewing Habits",
        "rarity": "Bronze"
    },
    {
        "id": "marathon_master",
        "title": "Season Marathoner",
        "icon": "ph-trophy",
        "description": "Finish an entire season of a show in under 48 hours",
        "category": "Viewing Habits",
        "rarity": "Gold"
    },
    {
        "id": "constant_streamer",
        "title": "Non-Stop Streamer",
        "icon": "ph-diamond",
        "description": "Log watch activity for 14 straight days",
        "category": "Viewing Habits",
        "rarity": "Platinum"
    },
    {
        "id": "speed_demon",
        "title": "Speed Demon",
        "icon": "ph-lightning",
        "description": "Watch video content at accelerated speed (1.25x+)",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "double_speed",
        "title": "Lightning Speed",
        "icon": "ph-trophy",
        "description": "Watch video at 2.0x maximum speed",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "slow_motion",
        "title": "Detail Analyst",
        "icon": "ph-trophy",
        "description": "Watch video at 0.5x slow-motion playback speed",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "sub_master",
        "title": "Subtitle Connoisseur",
        "icon": "ph-trophy",
        "description": "Apply custom subtitles to your playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "sub_styler",
        "title": "Subtitle Architect",
        "icon": "ph-trophy",
        "description": "Customize subtitle font size, text color, or box opacity",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "audio_enthusiast",
        "title": "Audio Specialist",
        "icon": "ph-trophy",
        "description": "Play media with multi-audio stream selection",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "volume_booster",
        "title": "Volume Overdrive",
        "icon": "ph-speaker-high",
        "description": "Boost audio volume past 100% up to 200% gain",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "skip_master",
        "title": "Skip Master",
        "icon": "ph-trophy",
        "description": "Use Skip Intro or Skip Outro feature during playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "skip_champion",
        "title": "Skip Champion",
        "icon": "ph-trophy",
        "description": "Use Skip Intro 10 or more times",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "fullscreen_pro",
        "title": "Immersion Master",
        "icon": "ph-corners-out",
        "description": "Toggle fullscreen mode for cinematic playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "resume_master",
        "title": "Resume Master",
        "icon": "ph-trophy",
        "description": "Resume playback from where you previously left off",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "quality_switcher",
        "title": "Resolution Switcher",
        "icon": "ph-gauge",
        "description": "Switch video quality streams mid-playback",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "hd_master",
        "title": "HD Purist",
        "icon": "ph-trophy",
        "description": "Watch content in 1080p Full HD resolution",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "four_k_king",
        "title": "4K Ultra HD King",
        "icon": "ph-trophy",
        "description": "Watch content in 4K Ultra HD resolution",
        "category": "Player Master",
        "rarity": "Platinum"
    },
    {
        "id": "seeker",
        "title": "Precision Seeker",
        "icon": "ph-trophy",
        "description": "Seek forward or backward using player controls",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "keyboard_ninja",
        "title": "Keyboard Ninja",
        "icon": "ph-trophy",
        "description": "Use keyboard shortcuts to control video",
        "category": "Player Master",
        "rarity": "Silver"
    },
    {
        "id": "pip_master",
        "title": "Multitasker",
        "icon": "ph-trophy",
        "description": "Use Picture-in-Picture or pop-out window controls",
        "category": "Player Master",
        "rarity": "Gold"
    },
    {
        "id": "mute_master",
        "title": "Stealth Mode",
        "icon": "ph-speaker-slash",
        "description": "Mute and unmute playback using player controls",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "next_ep_advance",
        "title": "Auto Advancer",
        "icon": "ph-trophy",
        "description": "Click Next Episode button to start subsequent episode",
        "category": "Player Master",
        "rarity": "Bronze"
    },
    {
        "id": "player_god",
        "title": "Player Grandmaster",
        "icon": "ph-trophy",
        "description": "Use all core player features (subtitles, audio, speed, quality)",
        "category": "Player Master",
        "rarity": "Platinum"
    },
    {
        "id": "movie_buff",
        "title": "Movie Buff",
        "icon": "ph-film-strip",
        "description": "Watch 3 or more Movie titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "series_addict",
        "title": "Series Addict",
        "icon": "ph-television",
        "description": "Watch 3 or more TV Series",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "otaku",
        "title": "Otaku Master",
        "icon": "ph-sparkle",
        "description": "Watch 3 or more Anime titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "explorer",
        "title": "Genre Explorer",
        "icon": "ph-compass",
        "description": "Watch titles across 3 or more distinct genres",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "genre_virtuoso",
        "title": "Genre Virtuoso",
        "icon": "ph-palette",
        "description": "Watch titles across 8 or more distinct genres",
        "category": "Discovery",
        "rarity": "Gold"
    },
    {
        "id": "action_junkie",
        "title": "Action Hero",
        "icon": "ph-sword",
        "description": "Watch 3 or more Action movies or series",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "comedy_lover",
        "title": "Laugh Track",
        "icon": "ph-smiley",
        "description": "Watch 3 or more Comedy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "drama_queen",
        "title": "Drama Enthusiast",
        "icon": "ph-mask-happy",
        "description": "Watch 3 or more Drama titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "sci_fi_fan",
        "title": "Sci-Fi Voyager",
        "icon": "ph-rocket",
        "description": "Watch 3 or more Sci-Fi & Fantasy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "horror_seeker",
        "title": "Thrill Seeker",
        "icon": "ph-ghost",
        "description": "Watch 3 or more Horror or Thriller titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "romance_hopeless",
        "title": "Hopeless Romantic",
        "icon": "ph-heart",
        "description": "Watch 3 or more Romance titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "docu_fanatic",
        "title": "Knowledge Seeker",
        "icon": "ph-graduation-cap",
        "description": "Watch 2 or more Documentary titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "animation_fan",
        "title": "Toon Collector",
        "icon": "ph-paint-brush",
        "description": "Watch 3 or more Animated movies or shows",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "crime_detective",
        "title": "Master Detective",
        "icon": "ph-detective",
        "description": "Watch 3 or more Crime or Mystery titles",
        "category": "Discovery",
        "rarity": "Silver"
    },
    {
        "id": "fantasy_realm",
        "title": "Realm Traveler",
        "icon": "ph-wand",
        "description": "Watch 3 or more Fantasy titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "trailer_buff",
        "title": "Trailer Aficionado",
        "icon": "ph-medal",
        "description": "Watch an official YouTube movie or show trailer",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "imdb_surfer",
        "title": "IMDb Explorer",
        "icon": "ph-medal",
        "description": "Click an IMDb link to view external movie metadata",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "search_master",
        "title": "Search Master",
        "icon": "ph-trophy",
        "description": "Use the search bar to find specific titles",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "filter_pro",
        "title": "Filter Pro",
        "icon": "ph-medal",
        "description": "Filter media by genre or media type in the library",
        "category": "Discovery",
        "rarity": "Bronze"
    },
    {
        "id": "omni_viewer",
        "title": "Omni Viewer",
        "icon": "ph-globe",
        "description": "Watch movies, series, and anime all on one profile",
        "category": "Discovery",
        "rarity": "Gold"
    },
    {
        "id": "curator",
        "title": "Master Curator",
        "icon": "ph-folder-star",
        "description": "Add 3 or more titles to Watchlist or Collections",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "collection_king",
        "title": "Collection Architect",
        "icon": "ph-folder",
        "description": "Create 3 or more custom media Collections",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "collection_empire",
        "title": "Collection Empire",
        "icon": "ph-archive",
        "description": "Create 10 or more custom media Collections",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "fav_collector",
        "title": "Favorite Hoarder",
        "icon": "ph-heart",
        "description": "Add 10 or more items to your Favorites list",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "fav_legend",
        "title": "Favorite Legend",
        "icon": "ph-diamond",
        "description": "Add 25 or more items to your Favorites list",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "trophy_collector",
        "title": "Trophy Collector",
        "icon": "ph-medal",
        "description": "Unlock 10 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "trophy_quarter",
        "title": "Trophy Specialist",
        "icon": "ph-trophy",
        "description": "Unlock 25 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "trophy_half",
        "title": "Trophy Master",
        "icon": "ph-star",
        "description": "Unlock 50 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "trophy_legend",
        "title": "Trophy Legend",
        "icon": "ph-crown",
        "description": "Unlock 75 or more achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Platinum"
    },
    {
        "id": "trophy_god",
        "title": "Grandmaster Completionist",
        "icon": "ph-diamond",
        "description": "Unlock all 100 achievements in your Trophy Case",
        "category": "Collector",
        "rarity": "Platinum"
    },
    {
        "id": "storage_gigabyte",
        "title": "Storage Saver",
        "icon": "ph-medal",
        "description": "Have over 10 GB of media mounted in your library",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "storage_terabyte",
        "title": "Terabyte Hoarder",
        "icon": "ph-trophy",
        "description": "Have over 100 GB of media mounted in your library",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "drive_mounter",
        "title": "Drive Mounter",
        "icon": "ph-medal",
        "description": "Mount external storage paths or drives to your library",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "multi_drive",
        "title": "Multi-Drive Collector",
        "icon": "ph-trophy",
        "description": "Mount 3 or more distinct media folders or drives",
        "category": "Collector",
        "rarity": "Gold"
    },
    {
        "id": "hd_collector",
        "title": "HD Vault",
        "icon": "ph-medal",
        "description": "Have at least 10 HD or 4K titles in your media library",
        "category": "Collector",
        "rarity": "Silver"
    },
    {
        "id": "profile_customizer",
        "title": "Profile Stylist",
        "icon": "ph-user",
        "description": "Customize your avatar icon or theme color",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "pin_defender",
        "title": "PIN Defender",
        "icon": "ph-shield-check",
        "description": "Secure your profile with a 4-digit security PIN",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "kids_creator",
        "title": "Family Guardian",
        "icon": "ph-baby",
        "description": "Create a Kids Safe Mode profile",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "scan_master",
        "title": "Library Scanner",
        "icon": "ph-trophy",
        "description": "Run a manual library disk scan from settings",
        "category": "Collector",
        "rarity": "Bronze"
    },
    {
        "id": "theme_master",
        "title": "Dark Mode Aficionado",
        "icon": "ph-trophy",
        "description": "Explore CapsStream premium dark theme interface",
        "category": "Collector",
        "rarity": "Bronze"
    }
]


KIDS_ACHIEVEMENTS = [
    # ─── 1. Little Milestones ───
    {
        "id": "kids_first_watch",
        "title": "Little Streamer",
        "icon": "ph-film-strip",
        "description": "Watch your very first cartoon or movie",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "kids_first_finish",
        "title": "Storybook Finisher",
        "icon": "ph-flag-checkered",
        "description": "Watch a show or movie all the way to the end",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "kids_time_1h",
        "title": "Cartoon Explorer",
        "icon": "ph-timer",
        "description": "Enjoy 1 hour of fun streaming",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "kids_time_3h",
        "title": "Adventure Fan",
        "icon": "ph-popcorn",
        "description": "Enjoy 3 hours of streaming fun",
        "category": "Little Milestones",
        "rarity": "Silver"
    },
    {
        "id": "kids_time_10h",
        "title": "Super Streamer",
        "icon": "ph-sparkle",
        "description": "Reach 10 hours of total streaming",
        "category": "Little Milestones",
        "rarity": "Gold"
    },
    {
        "id": "kids_time_25h",
        "title": "Mega Movie Star",
        "icon": "ph-rocket",
        "description": "Reach 25 hours of playtime",
        "category": "Little Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "kids_titles_5",
        "title": "Five Star Fun",
        "icon": "ph-star",
        "description": "Watch 5 different cartoons or movies",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "kids_titles_15",
        "title": "Show Collector",
        "icon": "ph-books",
        "description": "Watch 15 different cartoons or movies",
        "category": "Little Milestones",
        "rarity": "Silver"
    },
    {
        "id": "kids_titles_30",
        "title": "Library Champion",
        "icon": "ph-crown",
        "description": "Watch 30 different cartoons or movies",
        "category": "Little Milestones",
        "rarity": "Gold"
    },
    {
        "id": "kids_streak_2",
        "title": "Weekend Fan",
        "icon": "ph-confetti",
        "description": "Watch shows 2 days in a row",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },
    {
        "id": "kids_streak_3",
        "title": "Cartoon Streak",
        "icon": "ph-fire",
        "description": "Watch shows 3 days in a row",
        "category": "Little Milestones",
        "rarity": "Silver"
    },
    {
        "id": "kids_streak_5",
        "title": "High Five Streak",
        "icon": "ph-hand-palm",
        "description": "Stream every day for 5 days",
        "category": "Little Milestones",
        "rarity": "Gold"
    },
    {
        "id": "kids_streak_7",
        "title": "Weekly Champion",
        "icon": "ph-calendar",
        "description": "Stream every day for a full week",
        "category": "Little Milestones",
        "rarity": "Platinum"
    },
    {
        "id": "kids_quick_show",
        "title": "Quick Chuckles",
        "icon": "ph-lightning",
        "description": "Finish a short cartoon under 15 minutes",
        "category": "Little Milestones",
        "rarity": "Bronze"
    },

    # ─── 2. Cartoon Explorer ───
    {
        "id": "kids_animation_fan",
        "title": "Toon Lover",
        "icon": "ph-palette",
        "description": "Watch 3 or more Animated cartoons or shows",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_family_time",
        "title": "Family Fun",
        "icon": "ph-balloon",
        "description": "Watch 3 Family or Adventure movies",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_comedy_kid",
        "title": "Giggle Box",
        "icon": "ph-smiley",
        "description": "Watch 3 funny Comedy shows",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_fantasy_magic",
        "title": "Magic Kingdom",
        "icon": "ph-wand",
        "description": "Watch 3 Fantasy or magical adventures",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_sci_fi_space",
        "title": "Space Explorer",
        "icon": "ph-rocket",
        "description": "Watch 3 Sci-Fi or space adventures",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_genre_adventurer",
        "title": "Curious Explorer",
        "icon": "ph-magnifying-glass",
        "description": "Watch shows from 3 different categories",
        "category": "Cartoon Explorer",
        "rarity": "Silver"
    },
    {
        "id": "kids_trailer_scout",
        "title": "Sneak Peek",
        "icon": "ph-popcorn",
        "description": "Watch an official video preview or trailer",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_search_helper",
        "title": "Treasure Hunter",
        "icon": "ph-magnifying-glass",
        "description": "Search for your favorite cartoon or character",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },
    {
        "id": "kids_bubble_explorer",
        "title": "Bubble Popper",
        "icon": "ph-circles-three-plus",
        "description": "Click a category bubble on the Kids Home page",
        "category": "Cartoon Explorer",
        "rarity": "Bronze"
    },

    # ─── 3. Fun Player ───
    {
        "id": "kids_fullscreen_fun",
        "title": "Big Screen Magic",
        "icon": "ph-monitor",
        "description": "Play your video in full screen mode",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_play_pause",
        "title": "Freeze Dance",
        "icon": "ph-play-pause",
        "description": "Pause and resume your show",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_volume_whisper",
        "title": "Whisper Quiet",
        "icon": "ph-speaker-slash",
        "description": "Adjust the volume to a quiet level or mute",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_volume_party",
        "title": "Party Volume",
        "icon": "ph-speaker-high",
        "description": "Turn up the volume for your favorite song or scene",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_pip_hero",
        "title": "Mini Magic Screen",
        "icon": "ph-picture-in-picture",
        "description": "Open the video in a mini pop-out window",
        "category": "Fun Player",
        "rarity": "Silver"
    },
    {
        "id": "kids_next_episode",
        "title": "Next Adventure",
        "icon": "ph-skip-forward",
        "description": "Jump straight to the next episode",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_sub_reading",
        "title": "Reading Helper",
        "icon": "ph-chat-circle",
        "description": "Turn on subtitles to read along with the characters",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_speed_turbo",
        "title": "Turbo Speed",
        "icon": "ph-lightning",
        "description": "Watch a scene in fast speed",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_speed_slowmo",
        "title": "Super Slow-Mo",
        "icon": "ph-hare",
        "description": "Watch a scene in slow motion",
        "category": "Fun Player",
        "rarity": "Bronze"
    },
    {
        "id": "kids_rewind_seeker",
        "title": "Time Rewind",
        "icon": "ph-rewind",
        "description": "Rewind to replay a favorite part",
        "category": "Fun Player",
        "rarity": "Bronze"
    },

    # ─── 4. Sticker Collector ───
    {
        "id": "kids_fav_1",
        "title": "First Favorite",
        "icon": "ph-heart",
        "description": "Add your very first favorite cartoon",
        "category": "Sticker Collector",
        "rarity": "Bronze"
    },
    {
        "id": "kids_fav_5",
        "title": "Sticker Collection",
        "icon": "ph-heart",
        "description": "Save 5 shows to your Favorites",
        "category": "Sticker Collector",
        "rarity": "Silver"
    },
    {
        "id": "kids_fav_15",
        "title": "Super Treasure Box",
        "icon": "ph-diamond",
        "description": "Save 15 shows to your Favorites",
        "category": "Sticker Collector",
        "rarity": "Gold"
    },
    {
        "id": "kids_collection_builder",
        "title": "Toy Box Creator",
        "icon": "ph-folder-star",
        "description": "Create a custom cartoon playlist or collection",
        "category": "Sticker Collector",
        "rarity": "Silver"
    },
    {
        "id": "kids_avatar_dress",
        "title": "Dress Up Time",
        "icon": "ph-mask-happy",
        "description": "Choose a fun avatar icon or favorite color",
        "category": "Sticker Collector",
        "rarity": "Bronze"
    },

    # ─── 5. Junior Champion ───
    {
        "id": "kids_trophy_5",
        "title": "Little Star",
        "icon": "ph-star",
        "description": "Unlock 5 badges in your Kids Trophy Case",
        "category": "Junior Champion",
        "rarity": "Bronze"
    },
    {
        "id": "kids_trophy_10",
        "title": "Bronze Scout",
        "icon": "ph-medal",
        "description": "Unlock 10 badges in your Kids Trophy Case",
        "category": "Junior Champion",
        "rarity": "Bronze"
    },
    {
        "id": "kids_trophy_20",
        "title": "Silver Champion",
        "icon": "ph-medal",
        "description": "Unlock 20 badges in your Kids Trophy Case",
        "category": "Junior Champion",
        "rarity": "Silver"
    },
    {
        "id": "kids_trophy_30",
        "title": "Golden Superstar",
        "icon": "ph-trophy",
        "description": "Unlock 30 badges in your Kids Trophy Case",
        "category": "Junior Champion",
        "rarity": "Gold"
    },
    {
        "id": "kids_trophy_all",
        "title": "Ultimate Legend",
        "icon": "ph-crown",
        "description": "Collect all badges in the Kids Trophy Case!",
        "category": "Junior Champion",
        "rarity": "Platinum"
    }
]


ACTION_TO_KIDS_ACHIEVEMENTS = {
    "seeker": "kids_rewind_seeker",
    "fullscreen_pro": "kids_fullscreen_fun",
    "mute_master": "kids_volume_whisper",
    "volume_booster": "kids_volume_party",
    "pip_master": "kids_pip_hero",
    "next_ep_advance": "kids_next_episode",
    "sub_master": "kids_sub_reading",
    "sub_styler": "kids_sub_reading",
    "speed_demon": "kids_speed_turbo",
    "double_speed": "kids_speed_turbo",
    "slow_motion": "kids_speed_slowmo",
    "trailer_buff": "kids_trailer_scout",
    "search_master": "kids_search_helper",
    "filter_pro": "kids_genre_adventurer",
    "curator": "kids_fav_1",
    "fav_collector": "kids_fav_5",
    "fav_legend": "kids_fav_15",
    "collection_king": "kids_collection_builder",
    "profile_customizer": "kids_avatar_dress",
}


def get_profile_catalog(profile_id):
    conn = get_conn()
    p = conn.execute("SELECT is_kids FROM profiles WHERE id=?", (profile_id,)).fetchone()
    conn.close()
    return KIDS_ACHIEVEMENTS if (p and p["is_kids"]) else ACHIEVEMENTS


def unlock_achievement(profile_id, achievement_id):
    if not profile_id or not achievement_id:
        return None
    conn = get_conn()
    p_row = conn.execute("SELECT is_kids FROM profiles WHERE id=?", (profile_id,)).fetchone()
    is_kids = bool(p_row["is_kids"]) if p_row else False

    actual_aid = achievement_id
    if is_kids and achievement_id in ACTION_TO_KIDS_ACHIEVEMENTS:
        actual_aid = ACTION_TO_KIDS_ACHIEVEMENTS[achievement_id]

    active_catalog = KIDS_ACHIEVEMENTS if is_kids else ACHIEVEMENTS
    existing = conn.execute(
        "SELECT 1 FROM achievements WHERE profile_id=? AND achievement_id=?",
        (profile_id, actual_aid)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO achievements (profile_id, achievement_id) VALUES (?,?)",
            (profile_id, actual_aid)
        )
        conn.commit()
        conn.close()
        ach = next((a for a in active_catalog if a["id"] == actual_aid), None)
        if not ach:
            ach = next((a for a in (ACHIEVEMENTS + KIDS_ACHIEVEMENTS) if a["id"] == actual_aid), None)
        return ach
    conn.close()
    return None


def check_and_unlock_achievements(profile_id):
    from datetime import datetime
    conn = get_conn()

    p_row = conn.execute("SELECT avatar, color, is_kids, pin_hash FROM profiles WHERE id=?", (profile_id,)).fetchone()
    is_kids = bool(p_row["is_kids"]) if p_row else False

    unlocked_ids = set(
        r["achievement_id"] for r in conn.execute(
            "SELECT achievement_id FROM achievements WHERE profile_id=?", (profile_id,)
        ).fetchall()
    )

    new_unlocked = []

    stats_total = conn.execute("""
        SELECT SUM(position) as total_seconds, COUNT(*) as total_items, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) as completed_items
        FROM watch_progress WHERE profile_id=?
    """, (profile_id,)).fetchone()

    total_seconds = stats_total["total_seconds"] or 0
    total_items = stats_total["total_items"] or 0
    completed_items = stats_total["completed_items"] or 0

    fav_cnt = conn.execute("SELECT COUNT(*) as c FROM favorites WHERE profile_id=?", (profile_id,)).fetchone()["c"]
    col_cnt = conn.execute("SELECT COUNT(*) as c FROM collections WHERE profile_id=?", (profile_id,)).fetchone()["c"]

    raw_rows = conn.execute("""
        SELECT wp.updated_at, wp.position, wp.duration, wp.completed, wp.media_id,
               m.type, m.tmdb_id, m.season, m.episode, m.genres
        FROM watch_progress wp JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=?
    """, (profile_id,)).fetchall()

    day_hours = {}
    day_titles = {}
    day_seconds = {}
    day_movie_done = {}
    show_day_eps = {}
    hour_dates = {}
    genres_watched = {}
    max_episode_cache = {}

    for r in raw_rows:
        ts = r["updated_at"] or ""
        if len(ts) < 13:
            continue
        date_s, hour_s = ts[:10], ts[11:13]
        try:
            hour = int(hour_s)
        except ValueError:
            continue
        weekday = datetime.strptime(date_s, "%Y-%m-%d").weekday()

        day_hours.setdefault(date_s, set()).add(hour)
        day_titles.setdefault(date_s, set()).add(r["media_id"])
        hour_dates.setdefault(hour, set()).add(date_s)

        pos = r["position"] or 0
        dur = r["duration"] or 0
        day_seconds[date_s] = day_seconds.get(date_s, 0) + min(pos, dur) if dur else day_seconds.get(date_s, 0)

        if r["completed"] and r["type"] == "movie":
            day_movie_done[date_s] = day_movie_done.get(date_s, 0) + 1

        if r["completed"] and r["type"] != "movie" and r["tmdb_id"]:
            key = (r["tmdb_id"], r["season"], date_s)
            show_day_eps.setdefault(key, set()).add(r["episode"])

        for kw in ("Action", "Comedy", "Drama", "Science Fiction", "Sci-Fi", "Horror",
                   "Thriller", "Romance", "Documentary", "Animation",
                   "Crime", "Mystery", "Fantasy", "Family", "Adventure"):
            if kw in (r["genres"] or ""):
                genres_watched.setdefault(kw, set()).add(r["media_id"])

    genre_rows = conn.execute("""
        SELECT DISTINCT m.genres FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.genres IS NOT NULL
    """, (profile_id,)).fetchall()
    distinct_genres = set()
    for gr in genre_rows:
        for g in (gr["genres"] or "").split(","):
            if g.strip(): distinct_genres.add(g.strip())

    def consecutive_days(dates, needed):
        if len(dates) < needed:
            return False
        ds = sorted(datetime.strptime(d, "%Y-%m-%d").toordinal() for d in dates)
        run, best = 1, 1
        for i in range(1, len(ds)):
            run = run + 1 if ds[i] - ds[i - 1] == 1 else 1
            best = max(best, run)
        return best >= needed

    all_dates = set(day_hours.keys())

    # ─── Kids Mode Logic ───
    if is_kids:
        # 1. Little Milestones
        if "kids_first_watch" not in unlocked_ids and total_items > 0: new_unlocked.append("kids_first_watch")
        if "kids_first_finish" not in unlocked_ids and completed_items >= 1: new_unlocked.append("kids_first_finish")
        if "kids_time_1h" not in unlocked_ids and total_seconds >= 3600: new_unlocked.append("kids_time_1h")
        if "kids_time_3h" not in unlocked_ids and total_seconds >= 10800: new_unlocked.append("kids_time_3h")
        if "kids_time_10h" not in unlocked_ids and total_seconds >= 36000: new_unlocked.append("kids_time_10h")
        if "kids_time_25h" not in unlocked_ids and total_seconds >= 90000: new_unlocked.append("kids_time_25h")
        if "kids_titles_5" not in unlocked_ids and total_items >= 5: new_unlocked.append("kids_titles_5")
        if "kids_titles_15" not in unlocked_ids and total_items >= 15: new_unlocked.append("kids_titles_15")
        if "kids_titles_30" not in unlocked_ids and total_items >= 30: new_unlocked.append("kids_titles_30")
        if "kids_streak_2" not in unlocked_ids and consecutive_days(all_dates, 2): new_unlocked.append("kids_streak_2")
        if "kids_streak_3" not in unlocked_ids and consecutive_days(all_dates, 3): new_unlocked.append("kids_streak_3")
        if "kids_streak_5" not in unlocked_ids and consecutive_days(all_dates, 5): new_unlocked.append("kids_streak_5")
        if "kids_streak_7" not in unlocked_ids and consecutive_days(all_dates, 7): new_unlocked.append("kids_streak_7")
        if "kids_quick_show" not in unlocked_ids and any(
            r["completed"] and 0 < (r["duration"] or 0) <= 900 for r in raw_rows
        ):
            new_unlocked.append("kids_quick_show")

        # 2. Cartoon Explorer
        if "kids_animation_fan" not in unlocked_ids and len(genres_watched.get("Animation", set())) >= 3:
            new_unlocked.append("kids_animation_fan")
        fam_adv = genres_watched.get("Family", set()) | genres_watched.get("Adventure", set())
        if "kids_family_time" not in unlocked_ids and len(fam_adv) >= 3:
            new_unlocked.append("kids_family_time")
        if "kids_comedy_kid" not in unlocked_ids and len(genres_watched.get("Comedy", set())) >= 3:
            new_unlocked.append("kids_comedy_kid")
        if "kids_fantasy_magic" not in unlocked_ids and len(genres_watched.get("Fantasy", set())) >= 3:
            new_unlocked.append("kids_fantasy_magic")
        sci_fi = genres_watched.get("Science Fiction", set()) | genres_watched.get("Sci-Fi", set())
        if "kids_sci_fi_space" not in unlocked_ids and len(sci_fi) >= 3:
            new_unlocked.append("kids_sci_fi_space")
        if "kids_genre_adventurer" not in unlocked_ids and len(distinct_genres) >= 3:
            new_unlocked.append("kids_genre_adventurer")

        # 4. Sticker Collector
        if "kids_fav_1" not in unlocked_ids and fav_cnt >= 1: new_unlocked.append("kids_fav_1")
        if "kids_fav_5" not in unlocked_ids and fav_cnt >= 5: new_unlocked.append("kids_fav_5")
        if "kids_fav_15" not in unlocked_ids and fav_cnt >= 15: new_unlocked.append("kids_fav_15")
        if "kids_collection_builder" not in unlocked_ids and col_cnt >= 1: new_unlocked.append("kids_collection_builder")
        if "kids_avatar_dress" not in unlocked_ids and p_row and (
            (p_row["avatar"] or "").strip() or (p_row["color"] or "").strip()
        ):
            new_unlocked.append("kids_avatar_dress")

        # 5. Junior Champion (Kids Trophy Milestones)
        kids_ach_ids = {a["id"] for a in KIDS_ACHIEVEMENTS}
        current_kids_unlocked = len(unlocked_ids & kids_ach_ids) + len(new_unlocked)
        if "kids_trophy_5" not in unlocked_ids and current_kids_unlocked >= 5: new_unlocked.append("kids_trophy_5")
        if "kids_trophy_10" not in unlocked_ids and current_kids_unlocked >= 10: new_unlocked.append("kids_trophy_10")
        if "kids_trophy_20" not in unlocked_ids and current_kids_unlocked >= 20: new_unlocked.append("kids_trophy_20")
        if "kids_trophy_30" not in unlocked_ids and current_kids_unlocked >= 30: new_unlocked.append("kids_trophy_30")
        if "kids_trophy_all" not in unlocked_ids and current_kids_unlocked >= (len(KIDS_ACHIEVEMENTS) - 1):
            new_unlocked.append("kids_trophy_all")

        for aid in new_unlocked:
            conn.execute("INSERT OR IGNORE INTO achievements (profile_id, achievement_id) VALUES (?,?)", (profile_id, aid))

        if new_unlocked:
            conn.commit()
        conn.close()
        return new_unlocked

    # ─── Standard Mode Logic ───
    movie_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='movie'
    """, (profile_id,)).fetchone()["c"]

    series_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='series'
    """, (profile_id,)).fetchone()["c"]

    anime_cnt = conn.execute("""
        SELECT COUNT(*) as c FROM watch_progress wp
        JOIN media m ON m.id = wp.media_id
        WHERE wp.profile_id=? AND m.type='anime'
    """, (profile_id,)).fetchone()["c"]

    # 1. Milestones
    if "first_watch" not in unlocked_ids and total_items > 0: new_unlocked.append("first_watch")
    if "marathoner" not in unlocked_ids and total_seconds >= 18000: new_unlocked.append("marathoner")
    if "binge_master" not in unlocked_ids and total_seconds >= 86400: new_unlocked.append("binge_master")
    if "century_watcher" not in unlocked_ids and total_seconds >= 360000: new_unlocked.append("century_watcher")
    if "cinephile" not in unlocked_ids and completed_items >= 5: new_unlocked.append("cinephile")
    if "master_completer" not in unlocked_ids and completed_items >= 20: new_unlocked.append("master_completer")
    if "titan_completer" not in unlocked_ids and completed_items >= 50: new_unlocked.append("titan_completer")
    if "ten_titles" not in unlocked_ids and total_items >= 10: new_unlocked.append("ten_titles")
    if "fifty_titles" not in unlocked_ids and total_items >= 50: new_unlocked.append("fifty_titles")
    if "hundred_titles" not in unlocked_ids and total_items >= 100: new_unlocked.append("hundred_titles")
    if "first_finish" not in unlocked_ids and completed_items >= 1: new_unlocked.append("first_finish")
    if "credits_roll" not in unlocked_ids and completed_items >= 1: new_unlocked.append("credits_roll")

    # 2. Discovery
    if "movie_buff" not in unlocked_ids and movie_cnt >= 3: new_unlocked.append("movie_buff")
    if "series_addict" not in unlocked_ids and series_cnt >= 3: new_unlocked.append("series_addict")
    if "otaku" not in unlocked_ids and anime_cnt >= 3: new_unlocked.append("otaku")
    if "omni_viewer" not in unlocked_ids and (movie_cnt > 0 and series_cnt > 0 and anime_cnt > 0): new_unlocked.append("omni_viewer")

    if "explorer" not in unlocked_ids and len(distinct_genres) >= 3: new_unlocked.append("explorer")
    if "genre_virtuoso" not in unlocked_ids and len(distinct_genres) >= 8: new_unlocked.append("genre_virtuoso")

    # 3. Collector
    if "curator" not in unlocked_ids and (fav_cnt + col_cnt) >= 3: new_unlocked.append("curator")
    if "collection_king" not in unlocked_ids and col_cnt >= 3: new_unlocked.append("collection_king")
    if "collection_empire" not in unlocked_ids and col_cnt >= 10: new_unlocked.append("collection_empire")
    if "fav_collector" not in unlocked_ids and fav_cnt >= 10: new_unlocked.append("fav_collector")
    if "fav_legend" not in unlocked_ids and fav_cnt >= 25: new_unlocked.append("fav_legend")

    # 4. Viewing Habits
    if "night_owl" not in unlocked_ids:
        if conn.execute("SELECT 1 FROM watch_progress WHERE profile_id=? AND strftime('%H', updated_at) IN ('00','01','02','03','04')", (profile_id,)).fetchone():
            new_unlocked.append("night_owl")
    if "early_bird" not in unlocked_ids:
        if conn.execute("SELECT 1 FROM watch_progress WHERE profile_id=? AND strftime('%H', updated_at) IN ('05','06','07','08')", (profile_id,)).fetchone():
            new_unlocked.append("early_bird")

    # 5. Profile & Storage
    if p_row:
        if "pin_defender" not in unlocked_ids and p_row["pin_hash"]: new_unlocked.append("pin_defender")
        if "kids_creator" not in unlocked_ids and not p_row["is_kids"]:
            if conn.execute("SELECT 1 FROM profiles WHERE is_kids = 1").fetchone():
                new_unlocked.append("kids_creator")

    # 5b. Theme
    if "theme_master" not in unlocked_ids:
        new_unlocked.append("theme_master")

    # 5c. Library storage & drive milestones
    lib_stats = conn.execute("""
        SELECT COALESCE(SUM(file_size), 0) AS total_bytes,
               COUNT(DISTINCT CASE WHEN file_size >= 2000000000 THEN
                   COALESCE(tmdb_id, title) END) AS hd_titles
        FROM media
    """).fetchone()
    if "storage_gigabyte" not in unlocked_ids and lib_stats["total_bytes"] >= 10 * 1024**3:
        new_unlocked.append("storage_gigabyte")
    if "storage_terabyte" not in unlocked_ids and lib_stats["total_bytes"] >= 100 * 1024**3:
        new_unlocked.append("storage_terabyte")
    if "hd_collector" not in unlocked_ids and lib_stats["hd_titles"] >= 10:
        new_unlocked.append("hd_collector")

    drive_roots = {
        (row[0] or "")[:3] for row in conn.execute(
            "SELECT DISTINCT file_path FROM media WHERE file_path IS NOT NULL"
        ).fetchall()
    }
    if "drive_mounter" not in unlocked_ids and len(drive_roots) >= 2:
        new_unlocked.append("drive_mounter")
    if "multi_drive" not in unlocked_ids and len(drive_roots) >= 3:
        new_unlocked.append("multi_drive")
    if "profile_customizer" not in unlocked_ids and p_row and (
        (p_row["avatar"] or "").strip() or (p_row["color"] or "").strip()
    ):
        new_unlocked.append("profile_customizer")

    if "streak_3" not in unlocked_ids and consecutive_days(all_dates, 3): new_unlocked.append("streak_3")
    if "streak_7" not in unlocked_ids and consecutive_days(all_dates, 7): new_unlocked.append("streak_7")
    if "streak_30" not in unlocked_ids and consecutive_days(all_dates, 30): new_unlocked.append("streak_30")
    if "daily_dose" not in unlocked_ids and consecutive_days(all_dates, 5): new_unlocked.append("daily_dose")
    if "constant_streamer" not in unlocked_ids and consecutive_days(all_dates, 14): new_unlocked.append("constant_streamer")
    if "clockwork" not in unlocked_ids and any(len(hour_dates.get(h, set())) >= 3 for h in range(24)):
        new_unlocked.append("clockwork")

    if "midnight_marauder" not in unlocked_ids:
        if any(r["updated_at"][11:16] == "00:00" or (r["updated_at"][11:13] == "00" and int(r["updated_at"][14:16] or 99) < 10)
               for r in raw_rows if len(r["updated_at"] or "") >= 16):
            new_unlocked.append("midnight_marauder")
    if "lunchtime_streamer" not in unlocked_ids and any(12 <= h <= 13 for h in set().union(*day_hours.values()) if day_hours):
        new_unlocked.append("lunchtime_streamer")
    if "primetime_viewer" not in unlocked_ids and any(20 <= h <= 21 for h in set().union(*day_hours.values()) if day_hours):
        new_unlocked.append("primetime_viewer")
    if "dawn_patrol" not in unlocked_ids and any(5 <= h <= 6 for h in set().union(*day_hours.values()) if day_hours):
        new_unlocked.append("dawn_patrol")
    if "tea_time" not in unlocked_ids and any(
        15 <= h <= 16 and 0 < (r["duration"] or 0) <= 1800
        for r in raw_rows for h in [int(r["updated_at"][11:13])] if len(r["updated_at"] or "") >= 13
    ):
        new_unlocked.append("tea_time")
    if "afternoon_delight" not in unlocked_ids and any(
        r["type"] == "movie" and 14 <= int(r["updated_at"][11:13]) <= 16
        for r in raw_rows if len(r["updated_at"] or "") >= 13
    ):
        new_unlocked.append("afternoon_delight")
    if "friday_night" not in unlocked_ids and any(
        r["type"] == "movie" and datetime.strptime(r["updated_at"][:10], "%Y-%m-%d").weekday() == 4
        and int(r["updated_at"][11:13]) >= 18
        for r in raw_rows if len(r["updated_at"] or "") >= 13
    ):
        new_unlocked.append("friday_night")
    if "monday_blues" not in unlocked_ids and any(
        datetime.strptime(d, "%Y-%m-%d").weekday() == 0 for d in all_dates
    ):
        new_unlocked.append("monday_blues")
    if "weekend_warrior" not in unlocked_ids and any(
        datetime.strptime(d, "%Y-%m-%d").weekday() >= 5 and len(t) >= 5
        for d, t in day_titles.items()
    ):
        new_unlocked.append("weekend_warrior")
    if "holiday_binge" not in unlocked_ids and any(
        datetime.strptime(d, "%Y-%m-%d").weekday() >= 5 and len(t) >= 3
        for d, t in day_titles.items()
    ):
        new_unlocked.append("holiday_binge")
    if "all_nighter" not in unlocked_ids and any(
        (h1 in hours and h2 in hours)
        for d, hours in day_hours.items()
        for h1, h2 in [(1, 5), (1, 6), (2, 6)]
    ):
        new_unlocked.append("all_nighter")
    if "triple_threat" not in unlocked_ids and any(c >= 3 for c in day_movie_done.values()):
        new_unlocked.append("triple_threat")
    if "binge_session" not in unlocked_ids and any(len(e) >= 3 for e in show_day_eps.values()):
        new_unlocked.append("binge_session")
    if "quick_session" not in unlocked_ids and any(
        r["completed"] and 0 < (r["duration"] or 0) <= 900 for r in raw_rows
    ):
        new_unlocked.append("quick_session")
    if "long_session" not in unlocked_ids and any(s >= 7200 for s in day_seconds.values()):
        new_unlocked.append("long_session")
    if "marathon_session" not in unlocked_ids and any(s >= 14400 for s in day_seconds.values()):
        new_unlocked.append("marathon_session")
    if "silent_watcher" not in unlocked_ids and any(0 <= h <= 4 for h in set().union(*day_hours.values()) if day_hours):
        new_unlocked.append("silent_watcher")
    if "halfway_there" not in unlocked_ids and any(
        r["type"] in ("series", "anime") and (r["duration"] or 0) > 0
        and (r["position"] or 0) / r["duration"] >= 0.45
        for r in raw_rows
    ):
        new_unlocked.append("halfway_there")
    if "season_finale" not in unlocked_ids:
        for r in raw_rows:
            if not (r["completed"] and r["type"] != "movie" and r["tmdb_id"] and r["season"] is not None):
                continue
            cache_key = (r["tmdb_id"], r["season"])
            if cache_key not in max_episode_cache:
                row = conn.execute(
                    "SELECT MAX(episode) FROM media WHERE tmdb_id=? AND season=?",
                    (r["tmdb_id"], r["season"]),
                ).fetchone()
                max_episode_cache[cache_key] = row[0]
            if r["episode"] is not None and r["episode"] == max_episode_cache[cache_key]:
                new_unlocked.append("season_finale")
                break
    if "marathon_master" not in unlocked_ids:
        season_spans = {}
        for r in raw_rows:
            if r["completed"] and r["type"] != "movie" and r["tmdb_id"] and r["season"] is not None:
                key = (r["tmdb_id"], r["season"])
                span = season_spans.setdefault(key, {"dates": set(), "eps": set()})
                span["dates"].add(r["updated_at"][:10])
                span["eps"].add(r["episode"])
        for span in season_spans.values():
            if len(span["eps"]) >= 3 and len(span["dates"]) >= 1:
                ds = sorted(datetime.strptime(d, "%Y-%m-%d").toordinal() for d in span["dates"])
                if (ds[-1] - ds[0]) <= 2:
                    new_unlocked.append("marathon_master")
                    break

    genre_goals = {
        "action_junkie": (("Action",), 3),
        "comedy_lover": (("Comedy",), 3),
        "drama_queen": (("Drama",), 3),
        "sci_fi_fan": (("Science Fiction", "Sci-Fi"), 3),
        "horror_seeker": (("Horror", "Thriller"), 3),
        "romance_hopeless": (("Romance",), 3),
        "docu_fanatic": (("Documentary",), 2),
        "animation_fan": (("Animation",), 3),
        "crime_detective": (("Crime", "Mystery"), 3),
        "fantasy_realm": (("Fantasy",), 3),
    }
    for aid, (keywords, needed) in genre_goals.items():
        if aid in unlocked_ids:
            continue
        count = set()
        for kw in keywords:
            count |= genres_watched.get(kw, set())
        if len(count) >= needed:
            new_unlocked.append(aid)

    # 6. Trophy Case Collector Milestones
    current_total_unlocked = len(unlocked_ids) + len(new_unlocked)
    if "trophy_collector" not in unlocked_ids and current_total_unlocked >= 10: new_unlocked.append("trophy_collector")
    if "trophy_quarter" not in unlocked_ids and current_total_unlocked >= 25: new_unlocked.append("trophy_quarter")
    if "trophy_half" not in unlocked_ids and current_total_unlocked >= 50: new_unlocked.append("trophy_half")
    if "trophy_legend" not in unlocked_ids and current_total_unlocked >= 75: new_unlocked.append("trophy_legend")
    if "trophy_god" not in unlocked_ids and current_total_unlocked >= 99: new_unlocked.append("trophy_god")

    for aid in new_unlocked:
        conn.execute("INSERT OR IGNORE INTO achievements (profile_id, achievement_id) VALUES (?,?)", (profile_id, aid))

    if new_unlocked:
        conn.commit()

    conn.close()
    return new_unlocked


def get_profile_achievements(profile_id):
    conn = get_conn()
    check_and_unlock_achievements(profile_id)

    p_row = conn.execute("SELECT is_kids FROM profiles WHERE id=?", (profile_id,)).fetchone()
    is_kids = bool(p_row["is_kids"]) if p_row else False
    active_catalog = KIDS_ACHIEVEMENTS if is_kids else ACHIEVEMENTS

    unlocked_rows = conn.execute(
        "SELECT achievement_id, unlocked_at FROM achievements WHERE profile_id=?",
        (profile_id,)
    ).fetchall()
    conn.close()

    unlocked_map = {r["achievement_id"]: r["unlocked_at"] for r in unlocked_rows}

    results = []
    for ach in active_catalog:
        aid = ach["id"]
        is_unlocked = aid in unlocked_map
        unlocked_at_str = None
        if is_unlocked and unlocked_map[aid]:
            try:
                from datetime import datetime
                dt = datetime.strptime(str(unlocked_map[aid]).split(".")[0], "%Y-%m-%d %H:%M:%S")
                unlocked_at_str = dt.strftime("%b %d")
            except Exception:
                unlocked_at_str = "Unlocked"

        results.append({
            "id": aid,
            "title": ach["title"],
            "icon": ach["icon"],
            "description": ach["description"],
            "category": ach.get("category", "General"),
            "rarity": ach.get("rarity", "Bronze"),
            "unlocked": is_unlocked,
            "unlocked_at": unlocked_at_str
        })

    return results


