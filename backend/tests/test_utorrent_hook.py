# -*- coding: utf-8 -*-
"""
backend/tests/test_utorrent_hook.py — Test Suite for uTorrent Automation Hook.
"""
import unittest
from unittest.mock import patch, MagicMock
from backend.utorrent_hook import (
    match_torrent_to_request,
    process_utorrent_event,
    _extract_candidates
)


class TestUtorrentHook(unittest.TestCase):
    def setUp(self):
        self.sample_requests = [
            {
                "id": "req_movie_1",
                "title": "Runner",
                "type": "Movie",
                "year": "2026",
                "status": "pending",
                "admin_note": None
            },
            {
                "id": "req_movie_2",
                "title": "Spider-Man: Brand New Day",
                "type": "Movie",
                "year": "2026",
                "status": "pending",
                "admin_note": None
            },
            {
                "id": "req_tv_1",
                "title": "Severance",
                "type": "TV Show",
                "year": "2022",
                "season": 2,
                "episode": 1,
                "status": "pending",
                "admin_note": None
            },
            {
                "id": "req_movie_completed",
                "title": "Black Box",
                "type": "Movie",
                "year": "2026",
                "status": "completed",
                "completed_at": "2026-09-29 09:00:00",
                "admin_note": "Finished"
            }
        ]

    def test_extract_candidates(self):
        cands = _extract_candidates(
            name="Runner.2026.1080p.WEBRip.x264-GRP",
            filename="Runner.2026.mkv",
            dir_path="D:\\Downloads\\Runner.2026"
        )
        self.assertTrue(len(cands) >= 1)
        self.assertEqual(cands[0]["title"], "Runner")
        self.assertEqual(cands[0]["year"], 2026)

    def test_match_movie_exact_and_year(self):
        matched, reason, score = match_torrent_to_request(
            torrent_name="Runner.2026.1080p.WEBRip.x264-GRP",
            requests_list=self.sample_requests
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], "req_movie_1")
        self.assertGreaterEqual(score, 0.8)

    def test_match_movie_with_punctuation(self):
        matched, reason, score = match_torrent_to_request(
            torrent_name="Spider-Man.Brand.New.Day.2026.720p.HDTV.x264",
            requests_list=self.sample_requests
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], "req_movie_2")

    def test_match_tv_season_episode(self):
        matched, reason, score = match_torrent_to_request(
            torrent_name="Severance.S02E01.1080p.WEB-DL.x264",
            requests_list=self.sample_requests
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], "req_tv_1")

    def test_tv_season_mismatch_does_not_match(self):
        matched, reason, score = match_torrent_to_request(
            torrent_name="Severance.S01E01.1080p.WEB-DL.x264",
            requests_list=self.sample_requests
        )
        # S01E01 should not match the request for S02E01
        self.assertIsNone(matched)

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    @patch("backend.utorrent_hook.trigger_server_sync")
    def test_process_event_finished(self, mock_sync, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Runner.2026.1080p.WEBRip.x264-GRP",
            state=11  # Finished
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("updated"))
        self.assertEqual(res["request"]["status"], "completed")
        self.assertIsNotNone(res["request"]["completed_at"])
        self.assertIsNone(res["request"]["admin_note"])
        mock_save.assert_called_once()

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    @patch("backend.utorrent_hook.trigger_server_sync")
    def test_process_event_downloading_in_progress(self, mock_sync, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Spider-Man.Brand.New.Day.2026.720p.HDTV",
            state=6  # Downloading
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("updated"))
        self.assertEqual(res["request"]["status"], "in_progress")
        self.assertIsNone(res["request"]["admin_note"])
        mock_save.assert_called_once()

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_process_event_does_not_downgrade_completed(self, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Black.Box.2026.1080p.WEBRip",
            state=6  # Downloading
        )
        self.assertTrue(res["ok"])
        self.assertFalse(res.get("updated", False))
        mock_save.assert_not_called()

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    @patch("backend.utorrent_hook.is_supabase_configured", return_value=True)
    @patch("backend.utorrent_hook.update_online_request")
    @patch("backend.utorrent_hook.trigger_server_sync")
    def test_process_event_pushes_to_supabase(self, mock_sync, mock_sb_update, mock_sb_cfg, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]
        mock_sb_update.return_value = {"id": "req_movie_1", "status": "completed"}

        res = process_utorrent_event(
            torrent_name="Runner.2026.1080p.WEBRip",
            state=5  # Seeding
        )
        self.assertTrue(res["ok"])
        mock_sb_update.assert_called_once()
        args, kwargs = mock_sb_update.call_args
        self.assertEqual(args[0], "req_movie_1")
        self.assertEqual(args[1]["status"], "completed")

    @patch("urllib.request.urlopen")
    def test_trigger_server_sync_port_8700(self, mock_urlopen):
        from backend.utorrent_hook import trigger_server_sync
        mock_res = MagicMock()
        mock_res.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_res

        trigger_server_sync(port=8700)
        mock_urlopen.assert_called_once()
        req_obj = mock_urlopen.call_args[0][0]
        self.assertIn("127.0.0.1:8700", req_obj.full_url)
        self.assertIn("/api/requests/sync-library", req_obj.full_url)

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_trigger_server_sync_offline_silently_handled(self, mock_urlopen):
        from backend.utorrent_hook import trigger_server_sync
        # Should catch exception and not raise error when server is closed
        trigger_server_sync(port=8700)

    @patch("backend.utorrent_hook._should_suppress_notification", return_value=False)
    @patch("backend.utorrent_hook.show_windows_notification")
    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_process_event_triggers_notification(self, mock_save, mock_load, mock_notify, mock_suppress):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Runner.2026.1080p.WEBRip",
            state=11  # Finished
        )
        self.assertTrue(res["ok"])
        mock_notify.assert_called_once()
        title_arg, msg_arg = mock_notify.call_args[0]
        self.assertIn("Runner", msg_arg)
        self.assertIn("Completed", msg_arg)

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_process_event_state_20_moving_treated_as_finished(self, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        # State 20 is "Moving" when uTorrent finishes a torrent
        res = process_utorrent_event(
            torrent_name="Runner.2026.1080p.WEBRip",
            state=20
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("updated"))
        self.assertEqual(res["request"]["status"], "completed")

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_process_event_with_is_finish_flag_forces_completed(self, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Runner.2026.1080p.WEBRip",
            is_finish=True
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("updated"))
        self.assertEqual(res["request"]["status"], "completed")

    def test_resolve_torrent_status_messages(self):
        from backend.utorrent_hook import resolve_torrent_status
        # Status message string (%M) takes precedence and provides 100% precision
        self.assertEqual(resolve_torrent_status(status_msg="Downloading 55.4%"), "in_progress")
        self.assertEqual(resolve_torrent_status(status_msg="Seeding"), "completed")
        self.assertEqual(resolve_torrent_status(status_msg="Finished"), "completed")
        self.assertEqual(resolve_torrent_status(status_msg="Connecting to peers"), "in_progress")
        self.assertIsNone(resolve_torrent_status(status_msg="Queued"))
        self.assertIsNone(resolve_torrent_status(status_msg="Paused"))
        self.assertIsNone(resolve_torrent_status(status_msg="Stopped"))
        self.assertIsNone(resolve_torrent_status(status_msg="Error: Disk full"))

    def test_resolve_torrent_status_state_codes(self):
        from backend.utorrent_hook import resolve_torrent_status
        # Downloading states
        self.assertEqual(resolve_torrent_status(state=6), "in_progress")
        self.assertEqual(resolve_torrent_status(state=9), "in_progress")
        self.assertEqual(resolve_torrent_status(state=18), "in_progress")  # Downloading metadata
        # Finished states
        self.assertEqual(resolve_torrent_status(state=11), "completed")  # Finished
        self.assertEqual(resolve_torrent_status(state=5), "completed")   # Seeding
        self.assertEqual(resolve_torrent_status(state=20), "completed")  # Moving
        self.assertEqual(resolve_torrent_status(state=21), "completed")  # Flushing
        # Inactive / Queued states do not advance pending requests
        self.assertIsNone(resolve_torrent_status(state=12))  # Queued
        self.assertIsNone(resolve_torrent_status(state=3))   # Paused
        self.assertIsNone(resolve_torrent_status(state=13))  # Stopped
        self.assertIsNone(resolve_torrent_status(state=2))   # Checked

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_queued_state_does_not_falsely_mark_in_progress(self, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        # State 12 is Queued (waiting for slot), should not change status
        res = process_utorrent_event(
            torrent_name="Spider-Man.Brand.New.Day.2026.720p.HDTV",
            state=12
        )
        self.assertTrue(res["ok"])
        self.assertFalse(res.get("updated", False))
        mock_save.assert_not_called()

    @patch("backend.utorrent_hook.load_requests")
    @patch("backend.utorrent_hook.save_requests")
    def test_status_msg_downloading_marks_in_progress(self, mock_save, mock_load):
        mock_load.return_value = [dict(r) for r in self.sample_requests]

        res = process_utorrent_event(
            torrent_name="Spider-Man.Brand.New.Day.2026.720p.HDTV",
            status_msg="Downloading 74.3%"
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("updated"))
        self.assertEqual(res["request"]["status"], "in_progress")
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()

