import unittest
from backend.db import (
    ACHIEVEMENTS,
    KIDS_ACHIEVEMENTS,
    ACTION_TO_KIDS_ACHIEVEMENTS,
    get_profile_catalog,
    get_profile_achievements,
    unlock_achievement,
    check_and_unlock_achievements,
    create_profile,
    update_profile,
    get_conn
)

class TestAchievementsIntegrity(unittest.TestCase):
    def test_standard_achievements_have_triggers(self):
        with open('backend/db.py', 'r', encoding='utf-8') as f:
            db_code = f.read()
        with open('static/js/app.js', 'r', encoding='utf-8') as f:
            js_code = f.read()
        with open('app.py', 'r', encoding='utf-8') as f:
            app_code = f.read()

        check_fn_code = db_code[db_code.find('def check_and_unlock_achievements'):]

        missing = []
        for ach in ACHIEVEMENTS:
            aid = ach['id']
            in_db = (f'"{aid}"' in check_fn_code) or (f"'{aid}'" in check_fn_code)
            in_js = (f'"{aid}"' in js_code) or (f"'{aid}'" in js_code)
            in_app = (f'"{aid}"' in app_code) or (f"'{aid}'" in app_code)
            if not (in_db or in_js or in_app):
                missing.append(aid)

        print(f"Total standard achievements: {len(ACHIEVEMENTS)}")
        print(f"Missing triggers in standard: {missing}")
        self.assertEqual(missing, [], f"Orphan achievements detected in standard catalog: {missing}")

    def test_kids_achievements_have_triggers(self):
        with open('backend/db.py', 'r', encoding='utf-8') as f:
            db_code = f.read()
        with open('static/js/app.js', 'r', encoding='utf-8') as f:
            js_code = f.read()
        with open('app.py', 'r', encoding='utf-8') as f:
            app_code = f.read()

        check_fn_code = db_code[db_code.find('def check_and_unlock_achievements'):]

        missing = []
        for ach in KIDS_ACHIEVEMENTS:
            aid = ach['id']
            in_db = (f'"{aid}"' in check_fn_code) or (f"'{aid}'" in check_fn_code)
            in_action_map = aid in ACTION_TO_KIDS_ACHIEVEMENTS.values()
            in_js = (f'"{aid}"' in js_code) or (f"'{aid}'" in js_code)
            in_app = (f'"{aid}"' in app_code) or (f"'{aid}'" in app_code)
            if not (in_db or in_action_map or in_js or in_app):
                missing.append(aid)

        print(f"Total kids achievements: {len(KIDS_ACHIEVEMENTS)}")
        print(f"Missing triggers in kids: {missing}")
        self.assertEqual(missing, [], f"Orphan achievements detected in kids catalog: {missing}")

    def test_no_restricted_features_in_kids_achievements(self):
        for ach in KIDS_ACHIEVEMENTS:
            desc = (ach.get('description', '') + ' ' + ach.get('title', '')).lower()
            self.assertNotIn('pin', desc)
            self.assertNotIn('horror', desc)
            self.assertNotIn('crime', desc)
            self.assertNotIn('terabyte', desc)
            self.assertNotIn('gigabyte', desc)
            self.assertNotIn('settings', desc)

    def test_profile_catalog_and_unlocks(self):
        # Create a test standard profile and a test kids profile
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO profiles (name, is_kids, avatar, color) VALUES ('Test Adult', 0, '👤', '#e50914')")
        adult_pid = cur.lastrowid
        cur.execute("INSERT INTO profiles (name, is_kids, avatar, color) VALUES ('Test Kid', 1, '🧒', '#fdcb6e')")
        kid_pid = cur.lastrowid
        conn.commit()
        conn.close()

        try:
            # 1. Catalog retrieval
            self.assertEqual(len(get_profile_catalog(adult_pid)), len(ACHIEVEMENTS))
            self.assertEqual(len(get_profile_catalog(kid_pid)), len(KIDS_ACHIEVEMENTS))

            # 2. Direct unlock on kids profile
            kid_unlocked = unlock_achievement(kid_pid, "kids_bubble_explorer")
            self.assertIsNotNone(kid_unlocked)
            self.assertEqual(kid_unlocked["id"], "kids_bubble_explorer")

            # 3. Action mapping unlock on kids profile (e.g. 'fullscreen_pro' -> 'kids_fullscreen_fun')
            mapped_unlock = unlock_achievement(kid_pid, "fullscreen_pro")
            self.assertIsNotNone(mapped_unlock)
            self.assertEqual(mapped_unlock["id"], "kids_fullscreen_fun")

            # 4. Profile achievements retrieval
            kid_achievements = get_profile_achievements(kid_pid)
            self.assertEqual(len(kid_achievements), len(KIDS_ACHIEVEMENTS))
            unlocked_in_list = [a for a in kid_achievements if a["unlocked"]]
            unlocked_ids = {a["id"] for a in unlocked_in_list}
            self.assertIn("kids_bubble_explorer", unlocked_ids)
            self.assertIn("kids_fullscreen_fun", unlocked_ids)

            # 5. Adult profile achievements retrieval
            adult_achievements = get_profile_achievements(adult_pid)
            self.assertEqual(len(adult_achievements), len(ACHIEVEMENTS))
            adult_unlocked_ids = {a["id"] for a in adult_achievements if a["unlocked"]}
            self.assertIn("kids_creator", adult_unlocked_ids, "Family Guardian (kids_creator) should be unlocked for adult profiles when a Kids profile exists")

        finally:
            # Clean up test data
            conn = get_conn()
            conn.execute("DELETE FROM achievements WHERE profile_id IN (?,?)", (adult_pid, kid_pid))
            conn.execute("DELETE FROM profiles WHERE id IN (?,?)", (adult_pid, kid_pid))
            conn.commit()
            conn.close()

if __name__ == '__main__':
    unittest.main()
