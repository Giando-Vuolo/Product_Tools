"""Release Calendar (Epic 1): ICS parsing, release model, KPIs and the read-only page (no network)."""
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import release_calendar as rc  # noqa: E402

SAMPLE = (ROOT / "tests/fixtures/release_calendar/sample.ics").read_text(encoding="utf-8")
TODAY = date(2026, 11, 19)


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.cal = rc.parse_ics(SAMPLE)
        self.ev = rc.events_dataframe(self.cal)

    def test_header_and_counts(self):
        self.assertEqual(self.cal.name, "Sample Release Calendar")
        self.assertEqual(self.cal.timezone, "Europe/Madrid")
        # 14 VEVENTs: 1 cancelled dropped; series master + override become 3 occurrences -> 11 + 3
        self.assertEqual(len(self.cal.events), 14)
        self.assertNotIn("99.0.0", set(self.ev["Version"]))

    def test_all_day_end_is_inclusive(self):
        row = self.ev[self.ev["UID"] == "freeze-35@example"].iloc[0]
        self.assertEqual(row["Start"], pd.Timestamp("2026-10-23"))
        self.assertEqual(row["End"], pd.Timestamp("2026-11-06"))
        one_day = self.ev[self.ev["UID"] == "prod-36@example"].iloc[0]
        self.assertEqual(one_day["Start"], one_day["End"])

    def test_timed_event_uses_its_date(self):
        row = self.ev[self.ev["UID"] == "reg-36@example"].iloc[0]
        self.assertEqual((row["Start"], row["End"]), (pd.Timestamp("2026-11-10"),) * 2)

    def test_unfold_and_unescape(self):
        desc = self.ev[self.ev["UID"] == "prod-36@example"].iloc[0]["Description"]
        self.assertEqual(desc, "* Spring Boot\n* HTTPS, maybe?\n* Functional: multicountry")

    def test_recurrence_with_override(self):
        series = self.ev[self.ev["UID"] == "series@example"].sort_values("Start")
        self.assertEqual(list(series["Start"].dt.strftime("%Y-%m-%d")), ["2026-01-23", "2026-02-20", "2026-04-20"])
        self.assertEqual(series.iloc[2]["Summary"], "Deployment approval (moved)")

    def test_not_ics(self):
        with self.assertRaises(rc.CalendarError):
            rc.parse_ics('{"message":"Rate limit exceeded."}')

    def test_extract_version(self):
        cases = {"PROD | Release 31.0.0": "31.0.0", "Release 11.0": "11.0.0", "Pen Test Internal [35.1.0]": "35.1.0",
                 "Code Freeze Release 3x.x.0": "", "Christmas": "", "LT 37.0.0?": "37.0.0",
                 "Release 1.2.3.4": ""}
        for text, expected in cases.items():
            self.assertEqual(rc.extract_version(text), expected, text)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.ev = rc.events_dataframe(rc.parse_ics(SAMPLE))
        self.rel = rc.releases_dataframe(self.ev, TODAY)

    def test_one_row_per_version_sorted(self):
        self.assertEqual(list(self.rel["Version"]), ["35.0.0", "36.0.0", "37.0.0"])

    def test_steps_and_status(self):
        r35, r36, r37 = (self.rel.iloc[i] for i in range(3))
        self.assertEqual(r35["BAT"], pd.Timestamp("2026-10-28"))
        self.assertEqual(r35["Status"], "Deployed")
        self.assertEqual(r36["QS Freeze end"], pd.Timestamp("2026-12-15"))
        self.assertEqual(r36["Regression"], pd.Timestamp("2026-11-10"))
        self.assertEqual((r36["Status"], r36["Days to Prod"]), ("Planned", 26))
        self.assertEqual(r37["Status"], "No Prod date")
        self.assertTrue(pd.isna(r37["Days to Prod"]))

    def test_releases_display_merges_qs_freeze(self):
        shown = rc.releases_display(self.rel)
        self.assertNotIn("QS Freeze start", shown.columns)
        self.assertEqual(list(shown.columns[:2]), ["Version", "QS Freeze"])
        by_version = shown.set_index("Version")
        self.assertEqual(by_version.loc["36.0.0", "QS Freeze"], "2026-11-27 → 2026-12-15")
        self.assertEqual(by_version.loc["36.0.0", "Prod Deploy"], "2026-12-15")
        self.assertEqual(by_version.loc["36.0.0", "Pre Deploy"], "")  # missing step -> blank
        one_day = self.rel.copy()
        one_day.loc[0, "QS Freeze end"] = one_day.loc[0, "QS Freeze start"]
        self.assertEqual(rc.releases_display(one_day).loc[0, "QS Freeze"], "2026-10-23")

    def test_kpis(self):
        k = rc.calendar_kpis(self.ev, self.rel, TODAY)
        self.assertEqual((k["next_version"], k["days_to_next"]), ("36.0.0", 26))
        self.assertEqual(k["quarter_label"], "Q4 2026")
        self.assertEqual(k["prod_in_quarter"], 3)  # 35.0.0, 36.0.0, hotfix
        self.assertEqual(list(k["constraints_30d"]["Summary"]), ["PI Planning"])  # Christmas is > 30 days
        self.assertTrue(any("37.0.0" in w for w in k["warnings"]))
        self.assertTrue(any("Prod Deploy hotfix" in w for w in k["warnings"]))

    def test_past_release_without_prod_is_not_warned(self):
        k = rc.calendar_kpis(self.ev, self.rel, date(2027, 3, 1))
        self.assertFalse(any("37.0.0" in w for w in k["warnings"]))

    def test_filter(self):
        f = rc.filter_events(self.ev, date(2026, 12, 1), date(2026, 12, 31), ["Prod Deploy", "QS Freeze"])
        self.assertEqual(set(f["UID"]), {"freeze-36@example", "prod-36@example", "prod-nover@example"})
        self.assertEqual(list(rc.filter_events(self.ev, text="spring")["UID"]), ["prod-36@example"])

    def test_timeline_label_levels(self):
        ev = pd.DataFrame({
            "Start": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-06-01", "2026-01-01"]),
            "End": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-06-01", "2026-01-01"]),
            "Type": ["A", "A", "A", "A", "B"],
        })
        labels = ["Long title number one", "Second", "Third", "Far away", "Other row"]
        # 1, 2 and 3 collide -> levels 0, 1, 2; the far one and the other row go back to level 0
        self.assertEqual(rc.timeline_label_levels(ev, labels, chars_in_view=150), [0, 1, 2, 0, 0])
        # with only two levels the third takes the one that frees first (below: the long title runs further)
        self.assertEqual(rc.timeline_label_levels(ev, labels, chars_in_view=150, max_levels=2), [0, 1, 1, 0, 0])
        self.assertEqual(rc.timeline_label_levels(ev.iloc[0:0], []), [])

    def test_empty(self):
        empty = rc.events_dataframe(rc.Calendar("x", "", []))
        self.assertTrue(rc.releases_dataframe(empty, TODAY).empty)
        self.assertIsNone(rc.calendar_kpis(empty, rc.releases_dataframe(empty, TODAY), TODAY)["next_version"])


class FetchTests(unittest.TestCase):
    def _resp(self, status, text="", enc="utf-8"):
        m = MagicMock(status_code=status, text=text, encoding=enc)
        return m

    def test_missing_url(self):
        with self.assertRaisesRegex(rc.CalendarError, rc.ENV_ICS_URL):
            rc.fetch_ics("")

    def test_bearer_and_ok(self):
        with patch("utils.release_calendar.requests.get", return_value=self._resp(200, SAMPLE)) as get:
            self.assertIn("BEGIN:VCALENDAR", rc.fetch_ics("https://x/cal.ics", "Bearer abc", "Jira Server Token (Bearer)"))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer abc")
        self.assertIsNone(get.call_args.kwargs["auth"])

    def test_basic_auth(self):
        with patch("utils.release_calendar.requests.get", return_value=self._resp(200, SAMPLE)) as get:
            rc.fetch_ics("https://x/cal.ics", "tok", "Jira Cloud/Server Basic (Email/User + Token)", "me@x")
        self.assertEqual(get.call_args.kwargs["auth"], ("me@x", "tok"))

    def test_errors(self):
        for status, msg in ((429, "rate limit"), (401, "Access denied"), (500, "HTTP 500")):
            with patch("utils.release_calendar.requests.get", return_value=self._resp(status, "{}")):
                with self.assertRaisesRegex(rc.CalendarError, msg):
                    rc.fetch_ics("https://x/cal.ics", "t")
        with patch("utils.release_calendar.requests.get", return_value=self._resp(200, "<html>login</html>")):
            with self.assertRaisesRegex(rc.CalendarError, "iCalendar"):
                rc.fetch_ics("https://x/cal.ics", "t")


PAGE = str(ROOT / "tools/8_Release_Calendar.py")


class PageTests(unittest.TestCase):
    def _app(self, env):
        for p in (patch.dict(os.environ, env, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("requests.sessions.Session.request", side_effect=AssertionError("real network"))):
            p.start()
            self.addCleanup(p.stop)
        return AppTest.from_file(PAGE, default_timeout=30).run()

    def test_missing_config(self):
        at = self._app({})
        self.assertTrue(any(rc.ENV_ICS_URL in e.value and "Configuration" in e.value for e in at.error))

    def test_load_shows_kpis_and_tabs(self):
        with patch("utils.release_calendar.fetch_ics", return_value=SAMPLE) as fetch:
            at = self._app({rc.ENV_ICS_URL: "https://x/cal.ics", "CONFLUENCE_API_TOKEN": "t"})
            self.assertTrue(any("Load calendar" in i.value for i in at.info))
            at.button(key="rc_load").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        fetch.assert_called_once()
        self.assertEqual(len(at.metric), 4)
        self.assertEqual([t.label for t in at.tabs], ["Releases", "Jira", "Edit", "Events", "Timeline", "Overview"])
        self.assertEqual(len(at.dataframe), 3)  # Releases + Overview editors; Events shows the wrapped HTML table
        events_html = next(m.value for m in at.markdown if "rc-events" in m.value)
        self.assertIn('<td class="rc-desc">* Spring Boot\n* HTTPS, maybe?', events_html)
        at.toggle(key="rc_wrap").set_value(False).run()
        self.assertEqual(len(at.dataframe), 4)  # + interactive Events table
        self.assertTrue(at.toggle(key="rc_titles").value)

    def test_events_html_escapes_text(self):
        sample = SAMPLE.replace("SUMMARY:Christmas", "SUMMARY:<b>Xmas</b> & co")
        with patch("utils.release_calendar.fetch_ics", return_value=sample):
            at = self._app({rc.ENV_ICS_URL: "https://x/cal.ics"})
            at.button(key="rc_load").click().run()
            at.date_input(key="rc_range").set_value((date(2026, 1, 1), date(2027, 12, 31))).run()
        events_html = next(m.value for m in at.markdown if "rc-events" in m.value)
        self.assertIn("&lt;b&gt;Xmas&lt;/b&gt; &amp; co", events_html)
        self.assertNotIn("<b>Xmas</b>", events_html)

    def test_download_error_is_shown(self):
        with patch("utils.release_calendar.fetch_ics", side_effect=rc.CalendarError("Confluence rate limit (HTTP 429).")):
            at = self._app({rc.ENV_ICS_URL: "https://x/cal.ics"})
            at.button(key="rc_load").click().run()
        self.assertTrue(any("429" in e.value for e in at.error))


if __name__ == "__main__":
    unittest.main()


class ConfigurationFieldTests(unittest.TestCase):
    """Configuration → Confluence holds the ICS link as a secret field and saves it to .env."""

    def test_field_is_secret_and_saved(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertRegex(src, r'_secret_input\("Release Calendar ICS URL \(private\):", "release_calendar_ics_url"')
        self.assertIn('kv["RELEASE_CALENDAR_ICS_URL"] = st.session_state.release_calendar_ics_url', src)
        self.assertIn('os.getenv("RELEASE_CALENDAR_ICS_URL", "")', src)
        self.assertIn("st.session_state.release_calendar_ics_url != cics_in", src)
        # placed in the Confluence block, right after the Confluence token and before Ollama
        conf, ics, ollama = (src.index('"central_conf_token"'), src.index('"central_conf_ics"'),
                             src.index("Local AI (Ollama)"))
        self.assertLess(conf, ics)
        self.assertLess(ics, ollama)
