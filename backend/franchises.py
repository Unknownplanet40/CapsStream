"""
CapsStream — Smart Franchise & Cinematic Universe Engine
Curated definitions and dynamic matching for popular cinematic universes.
"""

import re
from typing import List, Dict, Any, Optional

UNIVERSES = [
    {
        "id": "universe-mcu",
        "name": "Marvel Cinematic Universe",
        "description": "Earth's mightiest heroes and the cosmic multiverse interconnected saga.",
        "icon": "ph ph-shield-star",
        "patterns": [
            r"\biron man\b",
            r"\bthe incredible hulk\b",
            r"\bthor\b",
            r"\bcaptain america\b",
            r"\bthe avengers\b",
            r"\bavengers\b",
            r"\bguardians of the galaxy\b",
            r"\bant-man\b",
            r"\bdoctor strange\b",
            r"\bdr\.? strange\b",
            r"\bspider-man\b",
            r"\bblack panther\b",
            r"\bcaptain marvel\b",
            r"\bblack widow\b",
            r"\bshang-chi\b",
            r"\beternals\b",
            r"\bwandavision\b",
            r"\bloki\b",
            r"\bthe falcon and the winter soldier\b",
            r"\bhawkeye\b",
            r"\bmoon knight\b",
            r"\bms\.? marvel\b",
            r"\bshe-hulk\b",
            r"\bsecret invasion\b",
            r"\bdeadpool & wolverine\b",
            r"\bdeadpool 3\b",
            r"\bthe marvels\b",
            r"\bwhat if\.\.\.\?\b",
            r"\becho\b",
            r"\bagatha\b"
        ],
        # Canonical In-Universe Timeline ranking
        "timeline_patterns": [
            (1, r"captain america:? the first avenger"),
            (2, r"captain marvel"),
            (3, r"iron man\b"),
            (4, r"iron man 2"),
            (5, r"the incredible hulk"),
            (6, r"thor\b"),
            (7, r"the avengers|avengers assemble"),
            (8, r"iron man 3"),
            (9, r"thor:? the dark world"),
            (10, r"captain america:? the winter soldier"),
            (11, r"guardians of the galaxy\b(?! vol)"),
            (12, r"guardians of the galaxy vol\.? 2"),
            (13, r"avengers:? age of ultron"),
            (14, r"ant-man\b"),
            (15, r"captain america:? civil war"),
            (16, r"black widow"),
            (17, r"black panther\b"),
            (18, r"spider-man:? homecoming"),
            (19, r"doctor strange\b"),
            (20, r"thor:? ragnarok"),
            (21, r"ant-man and the wasp\b(?!: quant)"),
            (22, r"avengers:? infinity war"),
            (23, r"avengers:? endgame"),
            (24, r"loki"),
            (25, r"what if"),
            (26, r"wandavision"),
            (27, r"the falcon and the winter soldier"),
            (28, r"spider-man:? far from home"),
            (29, r"shang-chi"),
            (30, r"eternals"),
            (31, r"spider-man:? no way home"),
            (32, r"doctor strange in the multiverse of madness"),
            (33, r"hawkeye"),
            (34, r"moon knight"),
            (35, r"ms\.? marvel"),
            (36, r"thor:? love and thunder"),
            (37, r"she-hulk"),
            (38, r"black panther:? wakanda forever"),
            (39, r"ant-man and the wasp:? quantumania"),
            (40, r"guardians of the galaxy vol\.? 3"),
            (41, r"secret invasion"),
            (42, r"the marvels"),
            (43, r"echo"),
            (44, r"deadpool & wolverine|deadpool 3"),
            (45, r"agatha all along"),
        ]
    },
    {
        "id": "universe-star-wars",
        "name": "Star Wars Saga",
        "description": "A long time ago in a galaxy far, far away... the epic battle between the Jedi and Sith.",
        "icon": "ph ph-sparkle",
        "patterns": [
            r"\bstar wars\b",
            r"\bthe phantom menace\b",
            r"\battack of the clones\b",
            r"\brevenge of the sith\b",
            r"\ba new hope\b",
            r"\bthe empire strikes back\b",
            r"\breturn of the jedi\b",
            r"\bthe force awakens\b",
            r"\bthe last jedi\b",
            r"\bthe rise of skywalker\b",
            r"\brogue one\b",
            r"\bsolo: a star wars story\b",
            r"\bthe mandalorian\b",
            r"\bandor\b",
            r"\bobi-wan kenobi\b",
            r"\bahsoka\b",
            r"\bthe book of boba fett\b",
            r"\bthe clone wars\b",
            r"\bthe bad batch\b",
            r"\bacolyte\b",
            r"\bskeleton crew\b"
        ],
        "timeline_patterns": [
            (1, r"the acolyte"),
            (2, r"star wars:? episode i|phantom menace"),
            (3, r"star wars:? episode ii|attack of the clones"),
            (4, r"star wars:? the clone wars"),
            (5, r"star wars:? episode iii|revenge of the sith"),
            (6, r"the bad batch"),
            (7, r"solo:? a star wars story"),
            (8, r"obi-wan kenobi"),
            (9, r"andor"),
            (10, r"star wars:? rebels"),
            (11, r"rogue one"),
            (12, r"star wars:? episode iv|a new hope"),
            (13, r"star wars:? episode v|empire strikes back"),
            (14, r"star wars:? episode vi|return of the jedi"),
            (15, r"the mandalorian"),
            (16, r"the book of boba fett"),
            (17, r"ahsoka"),
            (18, r"skeleton crew"),
            (19, r"star wars:? episode vii|the force awakens"),
            (20, r"star wars:? episode viii|the last jedi"),
            (21, r"star wars:? episode ix|rise of skywalker"),
        ]
    },
    {
        "id": "universe-dc",
        "name": "DC Universe & Batman",
        "description": "The heroes, vigilantes, and villains of Gotham, Metropolis, and beyond.",
        "icon": "ph ph-mask-happy",
        "patterns": [
            r"\bbatman\b",
            r"\bsuperman\b",
            r"\bwonder woman\b",
            r"\baquaman\b",
            r"\bflash\b",
            r"\bshazam\b",
            r"\bjustice league\b",
            r"\bsuicide squad\b",
            r"\bthe suicide squad\b",
            r"\bbirds of prey\b",
            r"\bblack adam\b",
            r"\bblue beetle\b",
            r"\bjoker\b",
            r"\bthe dark knight\b",
            r"\bman of steel\b",
            r"\bpeacemaker\b",
            r"\bthe penguin\b",
            r"\bconstantine\b",
            r"\bwatchmen\b"
        ]
    },
    {
        "id": "universe-wizarding-world",
        "name": "The Wizarding World",
        "description": "Magic, mystery, and legendary adventures at Hogwarts and throughout the wizarding world.",
        "icon": "ph ph-magic-wand",
        "patterns": [
            r"\bharry potter\b",
            r"\bfantastic beasts\b",
            r"\bthe secrets of dumbledore\b",
            r"\bthe crimes of grindelwald\b"
        ],
        "timeline_patterns": [
            (1, r"fantastic beasts and where to find them"),
            (2, r"the crimes of grindelwald"),
            (3, r"the secrets of dumbledore"),
            (4, r"sorcerer's stone|philosopher's stone"),
            (5, r"chamber of secrets"),
            (6, r"prisoner of azkaban"),
            (7, r"goblet of fire"),
            (8, r"order of the phoenix"),
            (9, r"half-blood prince"),
            (10, r"deathly hallows:? part 1"),
            (11, r"deathly hallows:? part 2"),
        ]
    },
    {
        "id": "universe-middle-earth",
        "name": "Middle-earth Saga",
        "description": "The epic fantasy journey through the Rings of Power, The Hobbit, and The Lord of the Rings.",
        "icon": "ph ph-sword",
        "patterns": [
            r"\blord of the rings\b",
            r"\bthe hobbit\b",
            r"\brings of power\b",
            r"\bfellowship of the ring\b",
            r"\bthe two towers\b",
            r"\breturn of the king\b",
            r"\ban unexpected journey\b",
            r"\bthe desolation of smaug\b",
            r"\bbattle of the five armies\b",
            r"\bthe war of the rohirrim\b"
        ],
        "timeline_patterns": [
            (1, r"rings of power"),
            (2, r"the war of the rohirrim"),
            (3, r"an unexpected journey"),
            (4, r"the desolation of smaug"),
            (5, r"the battle of the five armies"),
            (6, r"the fellowship of the ring"),
            (7, r"the two towers"),
            (8, r"the return of the king"),
        ]
    },
    {
        "id": "universe-ghibli",
        "name": "Studio Ghibli Collection",
        "description": "Enchanting hand-drawn animation masterpieces by Hayao Miyazaki and Isao Takahata.",
        "icon": "ph ph-leaf",
        "patterns": [
            r"\bspirited away\b",
            r"\bmy neighbor totoro\b",
            r"\bprincess mononoke\b",
            r"\bhowl's moving castle\b",
            r"\bkiki's delivery service\b",
            r"\bponyo\b",
            r"\bcastle in the sky\b",
            r"\bnausica\u00e4\b",
            r"\bgrave of the fireflies\b",
            r"\bporco rosso\b",
            r"\bwhisper of the heart\b",
            r"\bthe wind rises\b",
            r"\bthe boy and the heron\b",
            r"\bthe tale of the princess kaguya\b",
            r"\bwhen marnie was there\b",
            r"\bthe secret world of arrietty\b",
            r"\bfrom up on poppy hill\b",
            r"\bearwig and the witch\b",
            r"\bthe cat returns\b"
        ]
    },
    {
        "id": "universe-pixar",
        "name": "Pixar Animation Studios",
        "description": "Heartwarming stories and pioneering computer animation from the creators at Pixar.",
        "icon": "ph ph-lamp",
        "patterns": [
            r"\btoy story\b",
            r"\ba bug's life\b",
            r"\bmonsters,? inc\.?\b",
            r"\bmonsters university\b",
            r"\bfinding nemo\b",
            r"\bfinding dory\b",
            r"\bthe incredibles\b",
            r"\bincredibles 2\b",
            r"\bcars\b",
            r"\bratatouille\b",
            r"\bwall-e\b",
            r"\bup\b",
            r"\bbrave\b",
            r"\binside out\b",
            r"\bthe good dinosaur\b",
            r"\bcoco\b",
            r"\bonward\b",
            r"\bsoul\b",
            r"\bluca\b",
            r"\bturning red\b",
            r"\blightyear\b",
            r"\belemental\b",
            r"\belio\b"
        ]
    },
    {
        "id": "universe-monsterverse",
        "name": "MonsterVerse",
        "description": "Colossal clashes of the Titans featuring Godzilla, Kong, and prehistoric behemoths.",
        "icon": "ph ph-footprints",
        "patterns": [
            r"\bgodzilla\b",
            r"\bkong: skull island\b",
            r"\bgodzilla:? king of the monsters\b",
            r"\bgodzilla vs\.? kong\b",
            r"\bgodzilla x kong\b",
            r"\bmonarch:? legacy of monsters\b",
            r"\bskull island\b"
        ]
    },
    {
        "id": "universe-spiderman",
        "name": "Spider-Man & Spider-Verse",
        "description": "Every iteration of the web-slinger from Peter Parker to Miles Morales and the Spider-Verse.",
        "icon": "ph ph-globe-stand",
        "patterns": [
            r"\bspider-man\b",
            r"\bthe amazing spider-man\b",
            r"\binto the spider-verse\b",
            r"\bacross the spider-verse\b",
            r"\bbeyond the spider-verse\b",
            r"\bvenom\b",
            r"\bmorbius\b",
            r"\bmadame web\b",
            r"\bkraven the hunter\b"
        ]
    },
    {
        "id": "universe-007",
        "name": "James Bond 007",
        "description": "Licensed to kill: the legendary MI6 secret agent espionage film franchise.",
        "icon": "ph ph-crosshair",
        "patterns": [
            r"\b007\b",
            r"\bjames bond\b",
            r"\bdr\.? no\b",
            r"\bfrom russia with love\b",
            r"\bgoldfinger\b",
            r"\bthunderball\b",
            r"\byou only live twice\b",
            r"\bon her majesty's secret service\b",
            r"\bdiamonds are forever\b",
            r"\blive and let die\b",
            r"\bthe man with the golden gun\b",
            r"\bthe spy who loved me\b",
            r"\bmoonraker\b",
            r"\bfor your eyes only\b",
            r"\boctopussy\b",
            r"\ba view to a kill\b",
            r"\bthe living daylights\b",
            r"\blicence to kill\b",
            r"\bgoldeneye\b",
            r"\btomorrow never dies\b",
            r"\bthe world is not enough\b",
            r"\bdie another day\b",
            r"\bcasino royale\b",
            r"\bquantum of solace\b",
            r"\bskyfall\b",
            r"\bspectre\b",
            r"\bno time to die\b"
        ]
    },
    {
        "id": "universe-fast-furious",
        "name": "Fast & Furious Saga",
        "description": "High-octane heist action, supercar chases, and the power of family.",
        "icon": "ph ph-gauge",
        "patterns": [
            r"\bthe fast and the furious\b",
            r"\b2 fast 2 furious\b",
            r"\btokyo drift\b",
            r"\bfast & furious\b",
            r"\bfast five\b",
            r"\bfast & furious 6\b",
            r"\bfurious 7\b",
            r"\bthe fate of the furious\b",
            r"\bhobbs & shaw\b",
            r"\bf9\b",
            r"\bfast x\b"
        ]
    },
    {
        "id": "universe-jurassic",
        "name": "Jurassic Park & World",
        "description": "When prehistoric dinosaurs walk the Earth once more: 65 million years in the making.",
        "icon": "ph ph-dna",
        "patterns": [
            r"\bjurassic park\b",
            r"\bthe lost world:? jurassic park\b",
            r"\bjurassic park iii\b",
            r"\bjurassic world\b",
            r"\bfallen kingdom\b",
            r"\bdominion\b",
            r"\bcamp cretaceous\b",
            r"\bchaos theory\b"
        ]
    },
    {
        "id": "universe-alien-predator",
        "name": "Alien & Predator Universe",
        "description": "In space, no one can hear you scream: humanity's encounters with apex extraterrestrial hunters.",
        "icon": "ph ph-skull",
        "patterns": [
            r"\balien\b(?!:? covenant)?",
            r"\baliens\b",
            r"\balien 3|alien\^3\b",
            r"\balien resurrection\b",
            r"\bprometheus\b",
            r"\balien:? covenant\b",
            r"\balien:? romulus\b",
            r"\bpredator\b",
            r"\bpredator 2\b",
            r"\bpredators\b",
            r"\bthe predator\b",
            r"\bprey\b",
            r"\balien vs\.? predator\b",
            r"\bavp\b"
        ]
    },
    {
        "id": "universe-transformers",
        "name": "Transformers",
        "description": "Autobots and Decepticons waging their secret cybernetic war for the fate of Earth.",
        "icon": "ph ph-robot",
        "patterns": [
            r"\btransformers\b",
            r"\brevenge of the fallen\b",
            r"\bdark of the moon\b",
            r"\bage of extinction\b",
            r"\bthe last knight\b",
            r"\bbumblebee\b",
            r"\brise of the beasts\b",
            r"\btransformers one\b"
        ]
    },
    {
        "id": "universe-hunger-games",
        "name": "The Hunger Games",
        "description": "May the odds be ever in your favor: Panem and the rebellion against the Capitol.",
        "icon": "ph ph-flame",
        "patterns": [
            r"\bthe hunger games\b",
            r"\bcatching fire\b",
            r"\bmockingjay\b",
            r"\bthe ballad of songbirds\b"
        ]
    },
    {
        "id": "universe-mission-impossible",
        "name": "Mission: Impossible",
        "description": "Ethan Hunt and the IMF team undertaking breathtaking death-defying espionage missions.",
        "icon": "ph ph-parachute",
        "patterns": [
            r"\bmission:? impossible\b",
            r"\bghost protocol\b",
            r"\brogue nation\b",
            r"\bfallout\b",
            r"\bdead reckoning\b"
        ]
    },
    {
        "id": "universe-john-wick",
        "name": "John Wick Universe",
        "description": "The High Table, the Continental Hotel, and the underworld of master assassins.",
        "icon": "ph ph-target",
        "patterns": [
            r"\bjohn wick\b",
            r"\bthe continental\b",
            r"\bballerina\b"
        ]
    }
]


def _matches_patterns(title: str, patterns: List[str]) -> bool:
    """Check if title matches any pattern in the list."""
    if not title:
        return False
    title_lower = title.lower()
    for pat in patterns:
        if re.search(pat, title_lower):
            return True
    return False


def _get_timeline_rank(title: str, timeline_patterns: List[Any]) -> int:
    """Get the timeline sequence number for a title if it matches a timeline pattern."""
    if not title or not timeline_patterns:
        return 9999
    title_lower = title.lower()
    for rank, pat in timeline_patterns:
        if re.search(pat, title_lower):
            return rank
    return 9999


def get_universe_collections(library_items: List[Dict[str, Any]], min_count: int = 2) -> List[Dict[str, Any]]:
    """
    Scans library items and generates dynamic smart franchise collections
    for any universe or TMDb movie collection that meets the minimum count threshold (default: 2).
    """
    result = []
    # Deduplicate items by unique title or tmdb_id to avoid multiple episode copies
    unique_items = []
    seen = set()
    for item in library_items:
        key = item.get("tmdb_id") or item.get("id") or item.get("title")
        if key not in seen:
            seen.add(key)
            unique_items.append(dict(item))

    # Track item IDs already grouped into specific curated universes
    matched_universe_tmdb_ids = set()

    for universe in UNIVERSES:
        matched = []
        for item in unique_items:
            title = item.get("title", "")
            orig_title = item.get("original_title", "")
            if _matches_patterns(title, universe["patterns"]) or _matches_patterns(orig_title, universe["patterns"]):
                matched.append(item)

        if len(matched) >= min_count:
            for it in matched:
                if it.get("tmdb_id"):
                    matched_universe_tmdb_ids.add(it["tmdb_id"])

            # Sort by release year / added_at by default
            release_sorted = sorted(
                matched,
                key=lambda x: (x.get("year") or 0, x.get("added_at") or "", x.get("title") or "")
            )

            timeline_sorted = None
            has_timeline = bool(universe.get("timeline_patterns"))
            if has_timeline:
                timeline_sorted = sorted(
                    matched,
                    key=lambda x: (
                        _get_timeline_rank(x.get("title", ""), universe["timeline_patterns"]),
                        x.get("year") or 0,
                        x.get("title") or ""
                    )
                )

            result.append({
                "id": universe["id"],
                "name": universe["name"],
                "description": universe["description"],
                "icon": universe.get("icon", "ph ph-sparkle"),
                "poster_path": release_sorted[0].get("poster_path") if release_sorted else None,
                "backdrop_path": release_sorted[0].get("backdrop_path") if release_sorted else None,
                "smart": True,
                "universe": True,
                "has_timeline": has_timeline,
                "items": release_sorted,
                "item_count": len(release_sorted),
                "timeline_items": timeline_sorted,
            })

    # 2. Dynamic TMDb Movie Collections (belongs_to_collection)
    try:
        from backend.matcher import get_movie_collection
    except Exception:
        get_movie_collection = None

    if get_movie_collection:
        tmdb_collections: Dict[int, Dict[str, Any]] = {}
        for item in unique_items:
            if item.get("type") == "movie" and item.get("tmdb_id"):
                col = get_movie_collection(item["tmdb_id"])
                if col and isinstance(col, dict) and col.get("id"):
                    cid = col["id"]
                    if cid not in tmdb_collections:
                        tmdb_collections[cid] = {
                            "id": f"tmdb-col-{cid}",
                            "tmdb_collection_id": cid,
                            "name": col.get("name") or f"Franchise #{cid}",
                            "description": f"Official sequel & prequel collection from TMDb.",
                            "poster_path": col.get("poster_path") or item.get("poster_path"),
                            "backdrop_path": col.get("backdrop_path") or item.get("backdrop_path"),
                            "icon": "ph ph-film-strip",
                            "smart": True,
                            "universe": True,
                            "is_franchise": True,
                            "has_timeline": False,
                            "items": [],
                        }
                    tmdb_collections[cid]["items"].append(item)

        for cid, col_data in tmdb_collections.items():
            if len(col_data["items"]) >= min_count:
                # Check if this collection is entirely subsumed by an existing universe
                col_tmdb_ids = {it.get("tmdb_id") for it in col_data["items"] if it.get("tmdb_id")}
                if col_tmdb_ids.issubset(matched_universe_tmdb_ids) and len(col_tmdb_ids) > 0:
                    continue

                col_data["items"].sort(key=lambda x: (x.get("year") or 0, x.get("title") or ""))
                col_data["item_count"] = len(col_data["items"])
                result.append(col_data)

    return result


def get_media_franchise(media_item: Dict[str, Any], library_items: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """
    Finds the franchise/universe collection that contains this media item, if any.
    Returns the collection dict with all sibling sequels/prequels present in library.
    """
    if not media_item:
        return None

    if library_items is None:
        try:
            from backend.db import get_all_media
            library_items = get_all_media()
        except Exception:
            library_items = []

    if not library_items:
        return None

    all_collections = get_universe_collections(library_items, min_count=2)
    target_id = media_item.get("id")
    target_tmdb = media_item.get("tmdb_id")

    for col in all_collections:
        for item in col.get("items", []):
            if (target_id and item.get("id") == target_id) or (target_tmdb and item.get("tmdb_id") == target_tmdb):
                return {
                    "id": col["id"],
                    "name": col["name"],
                    "description": col.get("description", ""),
                    "poster_path": col.get("poster_path"),
                    "backdrop_path": col.get("backdrop_path"),
                    "icon": col.get("icon", "ph ph-sparkle"),
                    "smart": True,
                    "universe": True,
                    "item_count": len(col.get("items", [])),
                    "items": col.get("items", []),
                }

    return None
