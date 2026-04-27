import unittest

from manga_watch.availability import resolve_episode_availability, supported_availability_sources


class StaticHttpClient:
    def __init__(self, responses):
        self.responses = dict(responses)

    def get_text(self, url: str) -> str:
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url!r}")
        return self.responses[url]


class AvailabilityTests(unittest.TestCase):
    def test_supported_availability_sources_are_manga_sources_only(self):
        self.assertEqual(("comic-walker", "nicovideo-manga"), supported_availability_sources())
        self.assertNotIn("kakuyomu", supported_availability_sources())

    def test_comic_walker_resolves_exact_episode_url(self):
        seed_url = "https://comic-walker.com/detail/KC_004800_S"
        html = """
        <html><body>
          <a href="/detail/KC_004800_S/episodes/KC_0048000000100012_E">第１話</a>
          <a href="/detail/KC_004800_S/episodes/KC_0048000000200011_E">第2話①</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "comic-walker",
            seed_url,
            "1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual(
            {
                "source": "comic-walker",
                "status": "free_now",
                "url": "https://comic-walker.com/detail/KC_004800_S/episodes/KC_0048000000100012_E",
            },
            result,
        )

    def test_comic_walker_does_not_match_nearby_episode_number(self):
        seed_url = "https://comic-walker.com/detail/KC_004800_S"
        html = """
        <html><body>
          <a href="/detail/KC_004800_S/episodes/KC_0048000001000012_E">第10話</a>
          <a href="/detail/KC_004800_S/episodes/KC_0048000001100011_E">第11話</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "comic-walker",
            seed_url,
            "第1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual({"source": "comic-walker", "status": "not_found", "url": None}, result)

    def test_comic_walker_binds_episode_label_to_same_anchor(self):
        seed_url = "https://comic-walker.com/detail/KC_004800_S"
        html = """
        <html><body>
          <a href="/detail/KC_004800_S/episodes/KC_0048000000200011_E">第2話</a>
          <a href="/detail/KC_004800_S/episodes/KC_0048000000100012_E">第1話</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "comic-walker",
            seed_url,
            "第1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual(
            {
                "source": "comic-walker",
                "status": "free_now",
                "url": "https://comic-walker.com/detail/KC_004800_S/episodes/KC_0048000000100012_E",
            },
            result,
        )

    def test_nicovideo_manga_resolves_exact_episode_url(self):
        seed_url = "https://manga.nicovideo.jp/comic/62782"
        html = """
        <html><body>
          <a href="/watch/mg1000001">ニセモノの錬金術師 第1話 / 杉浦次郎</a>
          <a href="/watch/mg1000002">ニセモノの錬金術師 第2話 / 杉浦次郎</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "nicovideo-manga",
            seed_url,
            "第1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual(
            {
                "source": "nicovideo-manga",
                "status": "free_now",
                "url": "https://manga.nicovideo.jp/watch/mg1000001",
            },
            result,
        )

    def test_nicovideo_manga_does_not_match_nearby_episode_number(self):
        seed_url = "https://manga.nicovideo.jp/comic/62782"
        html = """
        <html><body>
          <a href="/watch/mg1000010">ニセモノの錬金術師 第10話 / 杉浦次郎</a>
          <a href="/watch/mg1000011">ニセモノの錬金術師 第11話 / 杉浦次郎</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "nicovideo-manga",
            seed_url,
            "1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual({"source": "nicovideo-manga", "status": "not_found", "url": None}, result)

    def test_nicovideo_manga_binds_episode_label_to_same_anchor(self):
        seed_url = "https://manga.nicovideo.jp/comic/62782"
        html = """
        <html><body>
          <a href="/watch/mg1000002">ニセモノの錬金術師 第2話 / 杉浦次郎</a>
          <a href="/watch/mg1000001">ニセモノの錬金術師 第1話 / 杉浦次郎</a>
        </body></html>
        """

        result = resolve_episode_availability(
            "nicovideo-manga",
            seed_url,
            "第1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual(
            {
                "source": "nicovideo-manga",
                "status": "free_now",
                "url": "https://manga.nicovideo.jp/watch/mg1000001",
            },
            result,
        )

    def test_returns_not_found_without_exact_episode(self):
        seed_url = "https://manga.nicovideo.jp/comic/62782"
        html = '<a href="/watch/mg1000002">ニセモノの錬金術師 第2話 / 杉浦次郎</a>'

        result = resolve_episode_availability(
            "nicovideo-manga",
            seed_url,
            "第1話",
            http_client=StaticHttpClient({seed_url: html}),
        )

        self.assertEqual({"source": "nicovideo-manga", "status": "not_found", "url": None}, result)

    def test_returns_unsupported_for_non_manga_or_unknown_source(self):
        result = resolve_episode_availability(
            "kakuyomu",
            "https://kakuyomu.jp/works/123",
            "第1話",
            http_client=StaticHttpClient({}),
        )

        self.assertEqual({"source": "kakuyomu", "status": "unsupported", "url": None}, result)


if __name__ == "__main__":
    unittest.main()
