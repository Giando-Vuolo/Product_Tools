import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils import release_plan_helpers as rp
from utils.confluence_helpers import get_confluence_page, list_child_pages, update_confluence_page
from utils.jira_helpers import fetch_release_issues_with_comments

FIX = Path(__file__).parent / "fixtures" / "release_plan"
JIRA = "https://jira.example.com/jira"
PARENT = "7177194568"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def response(payload, status=200):
    r = Mock()
    r.status_code = status
    r.json.return_value = payload
    r.text = json.dumps(payload)
    return r


class OfflineTestCase(unittest.TestCase):
    """Any un-mocked HTTP/socket use fails the test (AC36)."""

    def setUp(self):
        for target in ("requests.sessions.Session.request", "socket.socket.connect"):
            p = patch(target, side_effect=AssertionError("real network attempted"))
            p.start()
            self.addCleanup(p.stop)


class ParsingTests(OfflineTestCase):
    def test_case_variants_ac1(self):
        for tag in ("POST-ACTION:", "post-action:", "Post-Action:"):
            self.assertEqual(rp.parse_post_actions(f"{tag} Run migration X"), ["Run migration X"])

    def test_multiple_in_order_ac2(self):
        self.assertEqual(rp.parse_post_actions("POST-ACTION: a\nfoo\nPOST-ACTION: b\nPOST-ACTION: c"), ["a", "b", "c"])

    def test_rejected_forms_ac3(self):
        for text in ("<Post-action> text", "POST-ACTION text", "POST-ACTION:   ", "no tag here"):
            self.assertEqual(rp.parse_post_actions(text), [])

    def test_sources_and_authors_ac4_ac5(self):
        issue = {"key": "RECALLTWO-1", "fields": {
            "description": "POST-ACTION: from desc", "reporter": {"displayName": "Rita"},
            "comment": {"comments": [{"id": "9", "author": {"displayName": "Alice"}, "body": "POST-ACTION: from comment\nplain"}]}}}
        acts = rp.extract_actions_from_issue(issue)
        self.assertEqual([(a.text, a.author, a.source) for a in acts],
                         [("from desc", "Rita", "description"), ("from comment", "Alice", "comment:9")])

    def test_wiki_markup_ac6(self):
        self.assertEqual(rp.parse_post_actions("* POST-ACTION: Deploy X"), ["Deploy X"])
        self.assertEqual(rp.parse_post_actions("# POST-ACTION: Deploy X"), ["Deploy X"])
        self.assertEqual(rp.parse_post_actions("*POST-ACTION:* Run {{job}}"), ["Run job"])
        self.assertEqual(rp.parse_post_actions("POST-ACTION: see [docs|http://u]"), ["see docs"])
        self.assertEqual(rp.parse_post_actions("{code}\nPOST-ACTION: Run script\n{code}"), ["Run script"])

    def test_normalise_text(self):
        self.assertEqual(rp.normalise_text("  Foo   BAR "), "foo bar")


class JqlAndInputTests(OfflineTestCase):
    def test_jql_ac7(self):
        self.assertEqual(rp.build_release_jql("35.0.0"),
                         'project = RECALLTWO AND issuetype in (Bug, Improvement, Story, Task) AND fixVersion = "DIGITAL:HUB 35.0.0"')
        self.assertTrue(rp.build_release_jql("1.2.3", "P").endswith('fixVersion = "P 1.2.3"'))

    def test_version_ac8(self):
        self.assertEqual(rp.validate_version(" 35.0.0 "), "35.0.0")
        for bad in ("", "1.2", "1.2.3.4", "v1.2.3", "1.2.3-rc1"):
            with self.assertRaises(ValueError) as cm:
                rp.validate_version(bad)
            self.assertIn("X.Y.Z", str(cm.exception))

    def test_missing_config_ac37(self):
        self.assertEqual(rp.missing_config({"JIRA_SERVER": "x"}),
                         ["JIRA_API_TOKEN", "CONFLUENCE_SERVER", "CONFLUENCE_API_TOKEN", "RELEASE_PLAN_PARENT_PAGE"])
        self.assertEqual(rp.missing_config(dict.fromkeys(rp.REQUIRED_ENV, "v")), [])


class NetworkHelperTests(OfflineTestCase):
    def test_fetch_40_issues_paged_ac9(self):
        p1, p2 = load("jira_search_40_page1.json"), load("jira_search_40_page2.json")
        with patch("utils.jira_helpers.requests.get", side_effect=[response(p1), response(p2)]) as get:
            res = fetch_release_issues_with_comments(JIRA, "tok", "Jira Server Token (Bearer)", "", "jql", page_size=25)
        self.assertEqual(get.call_count, 2)
        self.assertEqual([c.kwargs["params"]["startAt"] for c in get.call_args_list], [0, 25])
        self.assertEqual(len(res["issues"]), 40)
        statuses = {i["fields"]["status"]["name"] for i in res["issues"]}
        self.assertEqual(len(statuses), 6)
        acts = rp.extract_actions(res["issues"])
        self.assertEqual(len({a.issue_key for a in acts}), 8)
        self.assertEqual(len(acts), 11)

    def test_comment_fallback(self):
        issue = {"key": "RECALLTWO-1", "fields": {"comment": {"comments": [], "total": 2}}}
        search = {"startAt": 0, "total": 1, "issues": [issue]}
        with patch("utils.jira_helpers.requests.get",
                   side_effect=[response(search), response(load("jira_issue_comments_paged.json"))]):
            res = fetch_release_issues_with_comments(JIRA, "tok", "x", "", "jql")
        self.assertEqual(len(res["issues"][0]["fields"]["comment"]["comments"]), 2)
        self.assertEqual(rp.extract_actions(res["issues"])[0].author, "Dana")

    def test_no_calls_without_config_ac37(self):
        with patch("utils.jira_helpers.requests.get") as g, patch("utils.confluence_helpers.requests.get") as g2, \
                patch("utils.confluence_helpers.requests.put") as p:
            self.assertIn("error", fetch_release_issues_with_comments("", "", "x", "", "j"))
            self.assertIn("error", get_confluence_page("", "", "x", "", "1"))
            self.assertIn("error", update_confluence_page("", "", "x", "", "1", "t", 2, "s"))
        g.assert_not_called()
        g2.assert_not_called()
        p.assert_not_called()

    def test_get_confluence_page(self):
        data = {"id": "5", "title": "T", "space": {"key": "RECALLTWO"}, "version": {"number": 3},
                "ancestors": [{"id": "1"}, {"id": "7177194568"}], "body": {"storage": {"value": "<p/>"}}}
        with patch("utils.confluence_helpers.requests.get", return_value=response(data)):
            page = get_confluence_page("https://c/confluence/", "tok", "x", "", "5")
        self.assertEqual((page["parent_id"], page["version"], page["space_key"], page["storage"]),
                         ("7177194568", 3, "RECALLTWO", "<p/>"))
        with patch("utils.confluence_helpers.requests.get", return_value=response({}, 404)):
            self.assertEqual(get_confluence_page("https://c", "tok", "x", "", "5"), {"error": "Page 5 not found"})

    def test_update_put_payload_ac19(self):
        with patch("utils.confluence_helpers.requests.put", return_value=response({})) as put:
            res = update_confluence_page("https://c/confluence/", "tok", "x", "", "7", "Title", 5, "<p>x</p>")
        self.assertEqual(res, {"ok": True, "version": 5})
        self.assertEqual(put.call_args.args[0], "https://c/confluence/rest/api/content/7")
        payload = put.call_args.kwargs["json"]
        self.assertEqual(payload["version"], {"number": 5})
        self.assertEqual(payload["body"]["storage"]["value"], "<p>x</p>")
        with patch("utils.confluence_helpers.requests.put", return_value=response({}, 409)):
            self.assertIn("HTTP 409", update_confluence_page("https://c", "tok", "x", "", "7", "T", 5, "s")["error"])


class GuardTests(OfflineTestCase):
    def guard(self, name, version="35.0.0", label=rp.DEFAULT_FIX_VERSION_LABEL):
        return rp.check_target_guard(load(name), version, label, parent_id=PARENT)

    def test_valid_targets_ac15(self):
        self.assertTrue(self.guard("confluence_page_34.json", "34.1.0").ok)
        self.assertTrue(self.guard("confluence_page_35.json").ok)
        g = self.guard("confluence_page_release_test.json")
        self.assertTrue(g.ok, g.errors)
        self.assertEqual(g.title, "Release test")

    def test_rejections_ac11(self):
        cases = {
            "confluence_page_other_space.json": "space",
            "confluence_page_grandchild.json": "grandchild",
            "confluence_page_parent.json": "parent page itself",
            "confluence_page_other_parent.json": "not under",
        }
        for name, text in cases.items():
            g = self.guard(name)
            self.assertFalse(g.ok, name)
            self.assertTrue(any(text in e for e in g.errors), (name, g.errors))
        g = rp.check_target_guard({"id": "1", "error": "Page 1 not found"}, "35.0.0", parent_id=PARENT)
        self.assertFalse(g.ok)

    def test_version_mismatch_ac12(self):
        g = self.guard("confluence_page_35.json", "36.0.0")
        self.assertFalse(g.ok)
        self.assertIn("expected 'DIGITAL:HUB 36.0.0', found 'DIGITAL:HUB 35.0.0'", g.errors[0])
        g = self.guard("confluence_page_no_macro.json")
        self.assertFalse(g.ok)
        self.assertIn("not found", g.errors[0])

    def test_label(self):
        self.assertFalse(self.guard("confluence_page_35.json", label="OTHER").ok)

    def test_template_always_blocked_ac13(self):
        page = load("confluence_page_template.json")  # JQL matches 35.0.0 and parent is valid
        g = rp.check_target_guard(page, "35.0.0", parent_id=PARENT)
        self.assertFalse(g.ok)
        self.assertTrue(any("Template" in e for e in g.errors))

    def test_no_update_when_guard_fails_ac14_ac17(self):
        update = Mock()
        res = rp.publish(lambda: load("confluence_page_template.json"), update, [], "35.0.0", rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertFalse(res["ok"])
        update.assert_not_called()
        # preview never writes either (it has no write path)
        pv = rp.build_preview(load("confluence_page_other_space.json"), [], "35.0.0", rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertIsNone(pv["plan"])


def act(key, text, author="Alice"):
    return rp.PostAction(key, text, author, "comment:1")

class ConfigTests(OfflineTestCase):
    def test_defaults_ac1_ac5(self):
        for env in ({"RELEASE_PLAN_PARENT_PAGE": "123"},
                    {"RELEASE_PLAN_PARENT_PAGE": "123", "RELEASE_FIXVERSION_LABEL": " ", "RELEASE_PLAN_TITLE_TEMPLATE": ""}):
            cfg = rp.load_release_plan_config(env)
            self.assertEqual((cfg.label, cfg.parent_id, cfg.title_template), ("DIGITAL:HUB", "123", "Release Plan {version}"))

    def test_overrides_ac2_ac6(self):
        cfg = rp.load_release_plan_config({"RELEASE_PLAN_PARENT_PAGE": "9", "RELEASE_FIXVERSION_LABEL": "ACME:X",
                                           "RELEASE_PLAN_TITLE_TEMPLATE": "RP {version}"})
        self.assertEqual(rp.build_fix_version("1.2.3", cfg.label), "ACME:X 1.2.3")
        self.assertEqual(rp.build_target_title(cfg.title_template, "1.2.3"), "RP 1.2.3")

    def test_parent_required_ac3(self):
        for env in ({}, {"RELEASE_PLAN_PARENT_PAGE": "  "}):
            with self.assertRaises(ValueError) as cm:
                rp.load_release_plan_config(env)
            self.assertIn("RELEASE_PLAN_PARENT_PAGE", str(cm.exception))
        with self.assertRaises(ValueError):
            rp.load_release_plan_config({"RELEASE_PLAN_PARENT_PAGE": "<PARENT_PAGE_ID>"})
        self.assertIn("RELEASE_PLAN_PARENT_PAGE", rp.missing_config({}))

    def test_template_needs_placeholder(self):
        with self.assertRaises(ValueError):
            rp.load_release_plan_config({"RELEASE_PLAN_PARENT_PAGE": "1", "RELEASE_PLAN_TITLE_TEMPLATE": "Plan"})

    def test_env_example_ac7(self):
        text = (Path(__file__).parent.parent / ".env.example").read_text(encoding="utf-8")
        self.assertIn("RELEASE PLAN POST-ACTIONS", text)
        self.assertIn("RELEASE_FIXVERSION_LABEL=DIGITAL:HUB", text)
        self.assertIn("RELEASE_PLAN_TITLE_TEMPLATE=Release Plan {version}", text)
        self.assertIn("RELEASE_PLAN_PARENT_PAGE=<PARENT_PAGE_ID>", text)
        self.assertNotIn("7177194568", text)


class DisplayTests(OfflineTestCase):
    def test_display_ac10_ac11(self):
        self.assertEqual(rp.fix_version_display("35.0.0", "DIGITAL:HUB"), "DIGITAL:HUB 35.0.0")
        self.assertEqual(rp.fix_version_display(" 35.0.0 ", "DIGITAL:HUB"), "DIGITAL:HUB 35.0.0")
        for bad in ("", "35.", "35.0", "v35.0.0", "35.0.0-rc1"):
            self.assertEqual(rp.fix_version_display(bad, "DIGITAL:HUB"), "")


class SelectTargetTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.children = [{"id": c["id"], "title": c["title"], "url": ""}
                         for c in load("confluence_children_parent.json")["results"]]

    def pick(self, version, children=None):
        title = rp.build_target_title(rp.DEFAULT_TITLE_TEMPLATE, version)
        return rp.select_target_page(self.children if children is None else children, title, PARENT)

    def test_exact_match_ac13(self):
        self.assertEqual(self.pick("35.0.0")["id"], "4")

    def test_no_substring_ac14(self):
        self.assertEqual(self.pick("3.0.0")["id"], "8")
        for v in ("2.0.0", "35.0", "5.0.0.1", "Database"):
            with self.assertRaises(ValueError):
                self.pick(v)
        with self.assertRaises(ValueError):
            self.pick("3.0.0", [c for c in self.children if c["id"] != "8"])

    def test_not_found_message_ac17(self):
        with self.assertRaises(ValueError) as cm:
            self.pick("40.0.0")
        self.assertEqual(str(cm.exception), f"Release Plan 40.0.0 not found under parent page {PARENT}.")

    def test_multiple_ac18(self):
        dup = self.children + [{"id": "99", "title": "Release Plan 35.0.0", "url": ""}]
        with self.assertRaises(ValueError) as cm:
            self.pick("35.0.0", dup)
        msg = str(cm.exception)
        self.assertIn("'Release Plan 35.0.0' (ID 4)", msg)
        self.assertIn("'Release Plan 35.0.0' (ID 99)", msg)

    def test_guard_mismatch_blocks_ac20(self):
        update = Mock()
        res = rp.publish(lambda: load("confluence_page_35.json"), update, [act("K-1", "x")], "36.0.0",
                         "DIGITAL:HUB", JIRA, PARENT)
        self.assertFalse(res["ok"])
        self.assertIn("mismatch", res["error"])
        update.assert_not_called()


class ListChildPagesTests(OfflineTestCase):
    def test_pagination_ac16(self):
        p1 = {"results": [{"id": "1", "title": "A", "_links": {"webui": "/a"}}, {"id": "2", "title": "B"}],
              "_links": {"next": "/rest/api/content/5/child/page?start=2"}}
        p2 = {"results": [{"id": "3", "title": "C"}], "_links": {}}
        with patch("utils.confluence_helpers.requests.get", side_effect=[response(p1), response(p2)]) as get:
            res = list_child_pages("https://c/confluence/", "tok", "x", "", "5", page_size=2)
        self.assertEqual([r["id"] for r in res["results"]], ["1", "2", "3"])
        self.assertEqual(res["results"][0]["url"], "https://c/confluence/a")
        self.assertEqual([c.kwargs["params"]["start"] for c in get.call_args_list], [0, 2])
        self.assertEqual(get.call_args_list[0].args[0], "https://c/confluence/rest/api/content/5/child/page")

    def test_error_and_no_call(self):
        with patch("utils.confluence_helpers.requests.get", return_value=response({}, 500)):
            self.assertIn("500", list_child_pages("https://c", "tok", "x", "", "5")["error"])
        with patch("utils.confluence_helpers.requests.get", return_value=response({}, 404)):
            self.assertIn("not found", list_child_pages("https://c", "tok", "x", "", "5")["error"])
        with patch("utils.confluence_helpers.requests.get") as g:
            self.assertIn("error", list_child_pages("", "", "x", "", "5"))
        g.assert_not_called()

    def test_fixture_shape(self):
        with patch("utils.confluence_helpers.requests.get", return_value=response(load("confluence_children_parent.json"))):
            res = list_child_pages("https://c", "tok", "x", "", PARENT)
        self.assertEqual(len(res["results"]), 9)


class MergeTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.page = load("confluence_page_35.json")
        self.storage = self.page["storage"]

    def test_task_format_and_escaping_ac20_ac21_ac24(self):
        xml = rp.render_task(5, act("RECALLTWO-1", "a <b> & \"c\" 'd'", "Bob <X>"), JIRA + "/")
        self.assertIn('<a href="https://jira.example.com/jira/browse/RECALLTWO-1">RECALLTWO-1</a>', xml)
        self.assertNotIn("jira/browse", xml.replace("jira/browse/RECALLTWO-1", ""))
        self.assertIn("incomplete", xml)
        self.assertNotIn("uuid", xml)
        self.assertNotIn("structured-macro", xml)
        self.assertIn("Bob &lt;X&gt;", xml)
        rp.assert_well_formed(xml)

    def test_merge_preserves_content_and_ids_ac22_ac23_ac24(self):
        plan = rp.plan_merge(self.storage, [act("RECALLTWO-1", "One"), act("RECALLTWO-2", "Two")], JIRA)
        self.assertEqual(plan.new_task_ids, [114, 115])
        inserted = "".join(rp.render_task(i, a, JIRA) for i, a in zip(plan.new_task_ids, plan.new_actions))
        self.assertEqual(plan.new_storage.replace(inserted, "", 1), self.storage)
        self.assertIn("<ac:task-id>9</ac:task-id><ac:task-uuid>abc-123</ac:task-uuid>", plan.new_storage)
        self.assertIn("<ac:task-body><p>Merge sync PRs</p></ac:task-body>", plan.new_storage)
        self.assertNotIn("task-uuid", inserted)

    def test_append_inside_existing_list_ac25(self):
        plan = rp.plan_merge(self.storage, [act("RECALLTWO-1", "One")], JIRA)
        self.assertIn("Merge sync PRs</p></ac:task-body></ac:task><ac:task><ac:task-id>114", plan.new_storage)
        self.assertEqual(plan.new_storage.count('<ul><li style="list-style-type: none;">'), 1)
        self.assertIn("</ac:task></ac:task-list></li></ul>", plan.new_storage)

    def test_no_tasklist_ac26(self):
        for name, first_id in (("confluence_page_no_tasklist.json", 51), ("confluence_page_empty_section.json", 51)):
            storage = load(name)["storage"]
            plan = rp.plan_merge(storage, [act("RECALLTWO-1", "One")], JIRA)
            self.assertEqual(plan.new_task_ids, [first_id])  # unrelated task id 50 elsewhere on page
            self.assertIn('</h2><ul><li style="list-style-type: none;"><ac:task-list><ac:task>', plan.new_storage)
            if "no_tasklist" in name:
                self.assertIn("<p>Nothing yet</p>", plan.new_storage)
        plan = rp.plan_merge("<h2>Post-actions</h2><p>x</p>", [act("K-1", "One")], JIRA)
        self.assertEqual(plan.new_task_ids, [1])

    def test_section_missing_ac27(self):
        with self.assertRaises(ValueError):
            rp.plan_merge(load("confluence_page_no_section.json")["storage"], [act("K-1", "x")], JIRA)
        update = Mock()
        res = rp.publish(lambda: load("confluence_page_no_section.json"), update, [act("K-1", "x")],
                         "35.0.0", rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertFalse(res["ok"])
        update.assert_not_called()

    def test_ambiguous_section(self):
        with self.assertRaises(ValueError):
            rp.plan_merge("<h2>Post-actions</h2><h2>Post-actions</h2>", [act("K-1", "x")], JIRA)

    def test_idempotent_ac28_ac29(self):
        first = rp.plan_merge(self.storage, [act("RECALLTWO-1", "Do it")], JIRA)
        second = rp.plan_merge(first.new_storage, [act("RECALLTWO-1", "  do   IT ")], JIRA)
        self.assertEqual(second.new_actions, [])
        self.assertEqual(len(second.skipped), 1)
        self.assertEqual(second.new_storage, first.new_storage)
        # checked (complete) task counts as present
        rt = load("confluence_page_release_test.json")["storage"]
        plan = rp.plan_merge(rt, [act("RECALLTWO-20001", "Run migration X")], JIRA)
        self.assertEqual(plan.new_actions, [])
        self.assertEqual(plan.new_storage, rt)

    def test_idempotent_author_with_parens_ac28(self):
        for author in ["O'Reilly)", "Smith (Ops)", "Doe):", "A): B (C"]:
            with self.subTest(author=author):
                a = act("RECALLTWO-1", "Deploy system", author)
                first = rp.plan_merge(self.storage, [a], JIRA)
                self.assertEqual(len(first.new_actions), 1)
                second = rp.plan_merge(first.new_storage, [a], JIRA)
                self.assertEqual(second.new_actions, [])
                self.assertEqual(len(second.skipped), 1)
                self.assertEqual(second.new_storage, first.new_storage)

    def test_text_with_paren_colon_idempotent(self):
        first = rp.plan_merge(self.storage, [act("RECALLTWO-1", "Deploy (x): now")], JIRA)
        again = rp.plan_merge(first.new_storage, [act("RECALLTWO-1", "Deploy (x): now")], JIRA)
        self.assertEqual(again.new_actions, [])
        other = rp.plan_merge(first.new_storage, [act("RECALLTWO-1", "Deploy (x): later")], JIRA)
        self.assertEqual(len(other.new_actions), 1)

    def test_cross_issue_and_run_duplicates_ac30_ac31(self):
        plan = rp.plan_merge(self.storage, [act("K-1", "Same"), act("K-2", "Same"), act("K-1", "same ")], JIRA)
        self.assertEqual([a.issue_key for a in plan.new_actions], ["K-1", "K-2"])
        self.assertEqual(len(plan.skipped), 1)

    def test_edited_text_is_new_ac32(self):
        first = rp.plan_merge(self.storage, [act("K-1", "Old text")], JIRA)
        second = rp.plan_merge(first.new_storage, [act("K-1", "New text")], JIRA)
        self.assertEqual(len(second.new_actions), 1)
        self.assertIn("Old text", second.new_storage)

    def test_manual_items_never_matched_ac33(self):
        plan = rp.plan_merge(self.storage, [act("K-1", "Merge sync PRs")], JIRA)
        self.assertEqual(len(plan.new_actions), 1)
        self.assertIn("<ac:task-body><p>Merge sync PRs</p></ac:task-body>", plan.new_storage)

    def test_no_actions_unchanged_ac18(self):
        plan = rp.plan_merge(self.storage, [], JIRA)
        self.assertEqual(plan.new_actions, [])
        self.assertEqual(plan.new_storage, self.storage)

    def test_existing_task_parsing_ac24(self):
        tasks = [t for _, _, t in rp.find_all_tasks(self.storage)]
        self.assertEqual([(t.task_id, t.text) for t in tasks],
                         [(50, "Unrelated"), (9, "Disable New Relic muting rule"), (113, "Merge sync PRs")])
        self.assertTrue(all(t.issue_key is None for t in tasks))


class PublishTests(OfflineTestCase):
    def test_publish_writes_version_plus_one_ac19(self):
        page = load("confluence_page_35.json")
        update = Mock(return_value={"ok": True})
        res = rp.publish(lambda: page, update, [act("K-1", "One")], "35.0.0", rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertEqual((res["ok"], res["added"]), (True, 1))
        pid, title, ver, storage = update.call_args.args
        self.assertEqual((pid, title, ver), ("8307795718", "Release Plan 35.0.0", 43))
        self.assertIn("K-1", storage)

    def test_publish_error_not_success_ac19(self):
        update = Mock(return_value={"error": "HTTP 409: conflict"})
        res = rp.publish(lambda: load("confluence_page_35.json"), update, [act("K-1", "One")], "35.0.0",
                         rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertFalse(res["ok"])
        self.assertIn("409", res["error"])

    def test_publish_no_new_is_noop_ac18(self):
        update = Mock()
        res = rp.publish(lambda: load("confluence_page_35.json"), update, [], "35.0.0",
                         rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertEqual((res["ok"], res["added"]), (True, 0))
        update.assert_not_called()

    def test_preview_does_not_write_ac16(self):
        pv = rp.build_preview(load("confluence_page_35.json"), [], "35.0.0", rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT)
        self.assertTrue(pv["guard"].ok)
        self.assertEqual(pv["plan"].new_actions, [])

    def test_english_messages_ac34(self):
        with self.assertRaises(ValueError) as cm:
            rp.validate_version("x")
        self.assertIn("Version must be", str(cm.exception))


class HeadingMatcherTests(OfflineTestCase):
    """AC28: Post-actions at h2, numbered h2, and h3 with emoji + numbering."""

    def _section(self, storage):
        h0, h1, end = rp.find_post_actions_section(storage)
        return storage[h0:h1]

    def test_normalise_heading(self):
        for raw in ("Post-actions", "5. Post-actions", "3.3 \u2699\ufe0f Post-actions",
                    "3.3 \U0001F6E0\ufe0f Post-actions", "\U0001F6E0\ufe0f 3.3 Post actions"):
            self.assertIn(rp._normalise_heading(raw), ("post-actions", "post actions"))

    def test_h2_old_page_34_and_35(self):
        for name in ("confluence_page_34.json", "confluence_page_35.json"):
            self.assertIn("Post-actions", self._section(load(name)["storage"]))

    def test_h3_with_emoji_999_v22(self):
        storage = load("confluence_page_999_v22.json")["storage"]
        h0, h1, end = rp.find_post_actions_section(storage)
        self.assertTrue(storage[h0:h1].startswith("<h3>3.3"))
        self.assertTrue(storage[end:].startswith("<h3>3.4"))

    def test_h3_section_ends_at_next_h3(self):
        storage = load("confluence_page_999_v22.json")["storage"]
        plan = rp.plan_merge(storage, [act("K-1", "One")], JIRA)
        self.assertEqual(len(plan.new_actions), 1)
        self.assertIn("K-1", plan.new_storage)


class SandboxGuardTests(OfflineTestCase):
    def test_accepted_versions_default_unchanged(self):
        page = load("confluence_page_35.json")
        self.assertTrue(rp.check_target_guard(page, "35.0.0", parent_id=PARENT).ok)
        self.assertFalse(rp.check_target_guard(page, "36.0.0", parent_id=PARENT).ok)

    def test_accepted_versions_999_v22(self):
        page = load("confluence_page_999_v22.json")
        self.assertFalse(rp.check_target_guard(page, "999.0.0", parent_id=PARENT).ok)
        g = rp.check_target_guard(page, "999.0.0", parent_id=PARENT, accepted_versions=("35.0.0",))
        self.assertTrue(g.ok, g.errors)


if __name__ == "__main__":
    unittest.main()
