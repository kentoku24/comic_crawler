import unittest

from manga_watch.piccoma_tracking import (
    extract_piccoma_authenticated_tracking,
    merge_piccoma_authenticated_tracking,
)


class PiccomaTrackingTests(unittest.TestCase):
    def test_extract_authenticated_tracking_reads_continue_position_and_charge_time(self):
        html = """
        <a class="js_readContinue"
           data-product_id="58170"
           data-current_episode_id="6212935"
           data-current_order_value="118"
           data-next_episode_id="6212936"
           data-next_order_value="119">続きから読む</a>
        <div id="js_freeChargeBar"
             data-server_time="2026-05-29 22:00:00"
             data-charge_time="2026-05-29 23:30:00"
             data-charge_duration="82800"></div>
        """

        tracking = extract_piccoma_authenticated_tracking(html, timezone_name="Asia/Tokyo")

        self.assertEqual(118, tracking["piccomaReadEpisodeNumber"])
        self.assertEqual("6212935", tracking["piccomaReadEpisodeId"])
        self.assertEqual(1780065000, tracking["piccomaWaitFreeNextRecoveryAt"])

    def test_merge_authenticated_tracking_keeps_latest_when_tracking_is_missing(self):
        latest = {"source": "piccoma", "latestKey": "piccoma:58170:episode:6212936"}

        self.assertEqual(latest, merge_piccoma_authenticated_tracking(latest, {}))

    def test_extract_authenticated_tracking_ignores_charge_time_without_read_position(self):
        html = """
        <div id="js_freeChargeBar"
             data-charge_time="2026-05-29 23:30:00"></div>
        """

        tracking = extract_piccoma_authenticated_tracking(html, timezone_name="Asia/Tokyo")

        self.assertEqual({}, tracking)


if __name__ == "__main__":
    unittest.main()
