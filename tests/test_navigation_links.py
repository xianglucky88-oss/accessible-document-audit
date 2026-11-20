import copy
import json
import unittest
from pathlib import Path

from accessible_document_audit import process

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "navigation-links.json"


class NavigationLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(SAMPLE.read_text(encoding="utf-8"))
        cls.facts = process("navigation-links", cls.source)
        cls.by_id = {fact["fact_id"]: fact for fact in cls.facts}

    def _entry(self, entry_id):
        return self.by_id[f"entry:{entry_id}"]

    def _coverage(self, language, chapter):
        return self.by_id[f"coverage:{language}:{chapter}"]

    def test_resolved_entries_identify_final_chapter_and_match_basis(self):
        direct = self._entry("nav-toc-01")
        self.assertEqual(direct["status"], "resolved")
        self.assertEqual(direct["final_chapter"], "ch-001")
        self.assertEqual(direct["matched_by"], "page")
        self.assertEqual(direct["arrival_language"], "zh")
        self.assertEqual(direct["requirement_result"], "required")
        self.assertIsNone(direct["issue"])

        via_alias = self._entry("nav-body-01")
        self.assertEqual(via_alias["final_chapter"], "ch-002")
        self.assertEqual(via_alias["matched_by"], "alias")

        # 转跳链：old-faq -> old-materials -> ch-002
        chained = self._entry("nav-body-06")
        self.assertEqual(chained["status"], "resolved")
        self.assertEqual(chained["final_chapter"], "ch-002")
        self.assertEqual(
            [(ref["kind"], ref["value"]) for ref in chained["resolution_path"]],
            [("alias", "old-faq"), ("alias", "old-materials")],
        )

    def test_shared_page_and_shared_alias_are_both_flagged_with_candidates(self):
        page_entry = self._entry("nav-body-03")
        self.assertEqual(page_entry["status"], "ambiguous")
        self.assertEqual(page_entry["issue"], "ambiguous-page")
        self.assertEqual([c["id"] for c in page_entry["candidates"]], ["ch-003", "ch-004"])

        alias_entry = self._entry("nav-body-02")
        self.assertEqual(alias_entry["status"], "ambiguous")
        self.assertEqual(alias_entry["issue"], "ambiguous-alias")
        self.assertEqual([c["id"] for c in alias_entry["candidates"]], ["ch-003", "ch-004"])

        # 同一旧别名经两条转跳声明落到两处内容
        declared = self._entry("nav-body-04")
        self.assertEqual(declared["status"], "ambiguous")
        self.assertEqual(declared["issue"], "ambiguous-declaration")
        self.assertEqual([c["id"] for c in declared["candidates"]], ["ch-003", "ch-004"])

        # 结构歧义事实保留全部候选与受影响入口
        page_amb = self.by_id["ambiguity:page:12"]
        self.assertEqual([c["id"] for c in page_amb["candidates"]], ["ch-003", "ch-004"])
        self.assertEqual(page_amb["entries"], ["nav-body-03", "nav-body-04", "nav-fr-04"])
        alias_amb = self.by_id["ambiguity:alias:shared-alias"]
        self.assertEqual(alias_amb["entries"], ["nav-body-02"])

    def test_redirect_that_returns_to_a_visited_target_is_a_cycle(self):
        entry = self._entry("nav-body-05")
        self.assertEqual(entry["status"], "cycle")
        self.assertEqual(entry["issue"], "redirect-cycle")
        self.assertEqual(
            [(ref["kind"], ref["value"]) for ref in entry["resolution_path"]],
            [("page", 30), ("page", 31), ("page", 30)],
        )
        cycle = self.by_id["cycle:page:30->page:31"]
        self.assertEqual(
            [(ref["kind"], ref["value"]) for ref in cycle["cycle_refs"]],
            [("page", 30), ("page", 31), ("page", 30)],
        )
        self.assertEqual(cycle["entries"], ["nav-body-05"])

    def test_unresolved_targets_keep_the_original_declaration_trace(self):
        bad_page = self._entry("nav-body-07")
        self.assertEqual(bad_page["status"], "unresolved")
        self.assertEqual(bad_page["issue"], "unknown-page")
        self.assertEqual(bad_page["declared_target"], {"kind": "page", "value": 99})

        bad_alias = self._entry("nav-body-08")
        self.assertEqual(bad_alias["status"], "unresolved")
        self.assertEqual(bad_alias["issue"], "unknown-alias")
        self.assertEqual(bad_alias["declared_target"], {"kind": "alias", "value": "missing-alias"})

    def test_required_chapters_without_usable_entries_and_their_attempts(self):
        unreachable = self._coverage("zh", "ch-005")
        self.assertFalse(unreachable["reachable"])
        self.assertEqual(unreachable["entries"], [])
        self.assertEqual(unreachable["attempting_entries"], [])

        # 歧义入口不能作为可用入口，但仍可从无入口章节反查到尝试过的入口
        for chapter in ("ch-003", "ch-004"):
            coverage = self._coverage("zh", chapter)
            self.assertFalse(coverage["reachable"])
            self.assertEqual(
                coverage["attempting_entries"], ["nav-body-02", "nav-body-03", "nav-body-04"]
            )

        self.assertFalse(self._coverage("fr", "fr-002")["reachable"])
        self.assertFalse(self._coverage("fr", "fr-003")["reachable"])

    def test_translation_fallback_lists_actual_arrival_language(self):
        fallback = self._entry("nav-fr-02")
        self.assertEqual(fallback["status"], "resolved")
        self.assertEqual(fallback["final_chapter"], "ch-002")
        self.assertEqual(fallback["requirement_result"], "source-fallback")
        self.assertEqual(fallback["arrival_language"], "zh")

        coverage = self._coverage("fr", "ch-002")
        self.assertTrue(coverage["reachable"])
        self.assertEqual(coverage["target_kind"], "source-fallback")
        self.assertEqual(coverage["arrival_language"], "zh")
        self.assertEqual(coverage["entries"], ["nav-fr-02"])

        # 未获许可的跨语言落章
        forbidden = self._entry("nav-body-10")
        self.assertEqual(forbidden["requirement_result"], "not-required")
        self.assertEqual(forbidden["issue"], "source-target-not-allowed")

    def test_errors_can_be_traced_back_to_entries_and_declarations(self):
        entry_ids = {fact["entry_id"] for fact in self.facts if fact["fact_id"].startswith("entry:")}
        self.assertEqual(len(entry_ids), len(self.source["entries"]))
        for fact in self.facts:
            if fact["fact_id"].startswith(("ambiguity:", "cycle:")):
                self.assertIn("entries", fact)
            if fact["fact_id"].startswith("entry:"):
                self.assertIn(fact["entry_id"], entry_ids)

    def test_completing_one_alias_changes_only_the_entries_routed_through_it(self):
        before = self.by_id["entry:nav-body-08"]
        self.assertEqual(before["status"], "unresolved")
        self.assertEqual(before["issue"], "unknown-alias")
        self.assertFalse(self._coverage("zh", "ch-005")["reachable"])

        repaired = copy.deepcopy(self.source)
        for chapter in repaired["structure"]:
            if chapter["id"] == "ch-005":
                chapter["aliases"] = ["missing-alias"]
        after_facts = process("navigation-links", repaired)
        after = {fact["fact_id"]: fact for fact in after_facts}

        fixed = after["entry:nav-body-08"]
        self.assertEqual(fixed["status"], "resolved")
        self.assertEqual(fixed["final_chapter"], "ch-005")
        self.assertEqual(fixed["matched_by"], "alias")
        self.assertEqual(fixed["requirement_result"], "required")
        self.assertTrue(after["coverage:zh:ch-005"]["reachable"])
        self.assertEqual(after["coverage:zh:ch-005"]["entries"], ["nav-body-08"])

        # 其他入口的去向不变
        untouched = [
            "entry:nav-toc-01", "entry:nav-body-01", "entry:nav-body-02", "entry:nav-body-03",
            "entry:nav-body-04", "entry:nav-body-05", "entry:nav-body-06", "entry:nav-body-07",
            "entry:nav-body-09", "entry:nav-body-10", "entry:nav-fr-01", "entry:nav-fr-02",
            "entry:nav-fr-03", "entry:nav-fr-04",
        ]
        for fact_id in untouched:
            self.assertEqual(
                after[fact_id]["status"], self.by_id[fact_id]["status"], fact_id
            )
            self.assertEqual(
                after[fact_id]["final_chapter"], self.by_id[fact_id]["final_chapter"], fact_id
            )

    def test_multiple_entries_may_legally_share_one_chapter(self):
        coverage = self._coverage("zh", "ch-002")
        self.assertTrue(coverage["reachable"])
        self.assertEqual(coverage["entries"], ["nav-body-01", "nav-body-06"])
        for entry_id in coverage["entries"]:
            self.assertEqual(self._entry(entry_id)["final_chapter"], "ch-002")

    def test_invalid_inputs_are_rejected(self):
        def reject(mutate, message):
            bad = copy.deepcopy(self.source)
            mutate(bad)
            with self.assertRaises(ValueError) as ctx:
                process("navigation-links", bad)
            self.assertIn(message, str(ctx.exception))

        reject(lambda d: d["structure"].append({"id": "ch-001", "title": "dup",
                                                 "language": "zh", "page": 1}), "duplicate chapter id")
        reject(lambda d: d["requirements"][0]["chapters"].append("ch-404"), "unknown chapter")
        reject(lambda d: d["entries"][0].__setitem__("language", "de"), "without requirements")

        no_license = copy.deepcopy(self.source)
        del no_license["requirements"][1]["source_target_allowed"]
        with self.assertRaises(ValueError):
            process("navigation-links", no_license)

        bad_ref = copy.deepcopy(self.source)
        bad_ref["entries"][0]["target"] = {"kind": "bookmark", "value": "x"}
        with self.assertRaises(ValueError):
            process("navigation-links", bad_ref)

    def test_output_is_deterministic(self):
        again = process("navigation-links", copy.deepcopy(self.source))
        self.assertEqual(again, self.facts)
        fact_ids = [fact["fact_id"] for fact in self.facts]
        self.assertEqual(fact_ids, sorted(fact_ids))


if __name__ == "__main__":
    unittest.main()
