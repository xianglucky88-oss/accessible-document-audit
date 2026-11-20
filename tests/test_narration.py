import unittest

from accessible_document_audit import process


def fragment(fid, paragraph="p", page=1, layout=1, start=0, end=1, text="x",
             continues_to=None):
    row = {"id": fid, "paragraph": paragraph, "page": page, "layout_order": layout,
           "start": start, "end": end, "text": text}
    if continues_to is not None:
        row["continues_to"] = continues_to
    return row


def declaration(fid, level, start, end, language):
    return {"id": fid, "level": level, "start": start, "end": end, "language": language}


def export(**sections):
    data = {"document_language": "zh-Hans", "fragments": []}
    data.update(sections)
    return data


def language_of(facts, fact_id):
    return next(fact for fact in facts if fact["fact_id"] == fact_id)


class NarrationLanguageTests(unittest.TestCase):
    def test_phrase_overrides_paragraph_overrides_document(self):
        data = export(
            fragments=[fragment("a", start=0, end=4, text="甲乙丙丁")],
            language_declarations=[
                declaration("pd", "paragraph", 0, 4, "fr"),
                declaration("wd", "phrase", 1, 3, "en"),
            ],
        )
        ranges = language_of(process("narration-language", data), "lang:p")["ranges"]
        self.assertEqual(
            [(r["start"], r["end"], r["language"], r["source"]) for r in ranges],
            [(0, 1, "fr", "paragraph"), (1, 3, "en", "phrase"), (3, 4, "fr", "paragraph")])

    def test_same_level_conflict_marks_only_overlap(self):
        data = export(
            fragments=[fragment("a", start=0, end=5, text="甲乙丙丁戊")],
            language_declarations=[
                declaration("d1", "phrase", 0, 3, "en"),
                declaration("d2", "phrase", 2, 5, "fr"),
            ],
        )
        ranges = language_of(process("narration-language", data), "lang:p")["ranges"]
        self.assertEqual(
            [(r["start"], r["end"], r["status"], r["language"]) for r in ranges],
            [(0, 2, "confirmed", "en"), (2, 3, "to_verify", None),
             (3, 5, "confirmed", "fr")])
        overlap = ranges[1]
        self.assertEqual(overlap["reason"], "conflicting phrase declarations")
        self.assertEqual(overlap["claims"], ["en", "fr"])
        self.assertEqual(overlap["declarations"], ["d1", "d2"])

    def test_cross_page_paragraph_keeps_local_declaration_in_its_range(self):
        data = export(
            fragments=[
                fragment("a", page=1, start=0, end=2, text="甲乙", continues_to="b"),
                fragment("b", page=2, start=2, end=4, text="丙丁"),
            ],
            language_declarations=[declaration("d1", "paragraph", 0, 2, "en")],
        )
        fact = language_of(process("narration-language", data), "lang:p")
        self.assertEqual(fact["pages"], [1, 2])
        self.assertEqual(
            [(r["start"], r["end"], r["language"], r["source"]) for r in fact["ranges"]],
            [(0, 2, "en", "paragraph"), (2, 4, "zh-Hans", "document")])

    def test_note_keeps_own_language_at_insertion(self):
        data = export(
            fragments=[fragment("a", start=0, end=2, text="甲乙")],
            margin_notes=[{"id": "n", "start": 10, "end": 15, "text": "Notes", "language": "en"}],
            citations=[{"id": "c", "note": "n", "anchor": "a", "page": 1, "layout_order": 2}],
        )
        facts = process("narration-text", data)
        note = language_of(facts, "text:note:n")
        self.assertEqual(note["language"][0]["language"], "en")
        body = language_of(facts, "text:0-2")
        self.assertEqual(body["language"][0]["language"], "zh-Hans")

    def test_spanning_and_dangling_declarations_are_unconfirmable(self):
        data = export(
            fragments=[fragment("a", start=0, end=2, text="甲乙")],
            margin_notes=[{"id": "n", "start": 10, "end": 12, "text": "注释"}],
            language_declarations=[
                declaration("wide", "phrase", 0, 12, "en"),
                declaration("void", "phrase", 50, 60, "fr"),
            ],
        )
        facts = process("narration-language", data)
        paragraph = language_of(facts, "lang:p")
        self.assertEqual(paragraph["ranges"][0]["language"], "zh-Hans")
        self.assertEqual(paragraph["unconfirmable"][0]["reason"],
                         "declaration spans multiple text units")
        dangling = language_of(facts, "lang:declaration:void")
        self.assertEqual(dangling["reason"], "no text at declared range")


class NarrationReadingOrderTests(unittest.TestCase):
    def test_duplicate_position_merges_but_same_text_elsewhere_is_kept(self):
        data = export(fragments=[
            fragment("a", start=0, end=2, text="相同", continues_to="b"),
            fragment("a2", start=0, end=2, text="相同", continues_to="b"),
            fragment("b", start=2, end=4, text="相同"),
        ])
        facts = process("narration-reading-order", data)
        merged = language_of(facts, "order:0-2")
        self.assertEqual(merged["member_exports"], ["a", "a2"])
        self.assertIsNotNone(language_of(facts, "order:2-4"))
        text_facts = process("narration-text", data)
        self.assertEqual([f["text"] for f in text_facts], ["相同", "相同"])

    def test_continuation_beats_layout_order(self):
        data = export(fragments=[
            fragment("a", layout=1, start=0, end=1, text="甲", continues_to="b"),
            fragment("b", layout=3, start=1, end=2, text="乙", continues_to="c"),
            fragment("c", layout=2, start=2, end=3, text="丙"),
        ])
        facts = process("narration-text", data)
        self.assertEqual([f["fact_id"] for f in facts],
                         ["text:0-1", "text:1-2", "text:2-3"])

    def test_contradictory_exports_keep_confirmed_order_and_language(self):
        data = export(
            fragments=[
                fragment("a", start=0, end=2, text="甲乙", continues_to="b1"),
                fragment("b1", start=2, end=4, text="丙丁", continues_to="c"),
                fragment("b2", start=2, end=4, text="丙戌", continues_to="c"),
                fragment("c", start=4, end=6, text="戊己"),
            ],
            language_declarations=[declaration("d", "phrase", 2, 4, "en")],
        )
        order = language_of(process("narration-reading-order", data), "order:2-4")
        self.assertEqual(order["status"], "to_verify")
        self.assertEqual(order["texts"], ["丙丁", "丙戌"])
        self.assertEqual(order["successor"], "order:4-6")
        disputes = [f for f in process("narration-reading-order", data)
                    if f["fact_id"].startswith("dispute:")]
        self.assertEqual([d["type"] for d in disputes], ["contradictory_exports"])
        segment = language_of(process("narration-text", data), "text:2-4")
        self.assertEqual(segment["continuity"], "confirmed")
        self.assertEqual(segment["language"][0]["language"], "en")
        self.assertEqual(segment["text_status"], "to_verify")

    def test_fork_broken_and_loop_are_disputes_not_silent_choices(self):
        data = export(fragments=[
            fragment("a", layout=1, start=0, end=1, text="甲", continues_to="t"),
            fragment("b", layout=2, start=1, end=2, text="乙", continues_to="t"),
            fragment("t", layout=3, start=2, end=3, text="丙", continues_to="gone"),
            fragment("l1", layout=4, start=3, end=4, text="丁", continues_to="l2"),
            fragment("l2", layout=5, start=4, end=5, text="戊", continues_to="l1"),
        ])
        facts = process("narration-reading-order", data)
        by_id = {f["fact_id"]: f for f in facts}
        fork = by_id["dispute:fork:2-3"]
        self.assertEqual(fork["predecessors"], ["order:0-1", "order:1-2"])
        self.assertEqual(by_id["dispute:broken_continuation:2-3"]["missing_target"], "gone")
        self.assertEqual(by_id["dispute:loop:3-4"]["members"],
                         ["order:3-4", "order:4-5"])
        target = by_id["order:2-3"]
        self.assertEqual(target["predecessor_candidates"], ["order:0-1", "order:1-2"])
        text_facts = {f["fact_id"]: f for f in process("narration-text", data)}
        self.assertEqual(text_facts["text:0-1"]["continuity"], "fork")
        self.assertEqual(text_facts["text:2-3"]["continuity"], "broken")
        self.assertEqual(text_facts["text:3-4"]["continuity"], "loop")
        self.assertEqual(text_facts["text:4-5"]["continues_to"], "text:3-4")

    def test_shared_note_reads_once_at_first_confirmable_citation(self):
        data = export(
            fragments=[
                fragment("a", layout=1, start=0, end=1, text="甲"),
                fragment("b", layout=2, start=1, end=2, text="乙"),
            ],
            margin_notes=[{"id": "n", "start": 10, "end": 12, "text": "注释"}],
            citations=[
                {"id": "c2", "note": "n", "anchor": "b", "page": 1, "layout_order": 5},
                {"id": "c1", "note": "n", "anchor": "a", "page": 1, "layout_order": 3},
            ],
        )
        facts = process("narration-reading-order", data)
        note = language_of(facts, "note:n")
        self.assertEqual(note["read_at"], "c1")
        self.assertEqual(note["traced_from"], ["c2"])
        self.assertEqual(note["inserted_after"], "text:0-1")

    def test_tied_citations_keep_candidates(self):
        data = export(
            fragments=[
                fragment("a", layout=1, start=0, end=1, text="甲"),
                fragment("b", layout=2, start=1, end=2, text="乙"),
            ],
            margin_notes=[{"id": "n", "start": 10, "end": 12, "text": "注释"}],
            citations=[
                {"id": "c1", "note": "n", "anchor": "a", "page": 1, "layout_order": 3},
                {"id": "c2", "note": "n", "anchor": "b", "page": 1, "layout_order": 3},
            ],
        )
        facts = process("narration-reading-order", data)
        note = language_of(facts, "note:n")
        self.assertEqual(note["status"], "to_verify")
        self.assertEqual(note["candidates"], ["c1", "c2"])
        dispute = language_of(facts, "dispute:citation_order:n")
        self.assertEqual(dispute["candidates"], ["c1", "c2"])
        segment = language_of(process("narration-text", data), "text:note:n")
        self.assertFalse(segment["position_confirmed"])
        self.assertEqual(segment["candidates"], ["c1", "c2"])


class NarrationValidationTests(unittest.TestCase):
    def test_overlapping_fragments_are_rejected(self):
        data = export(fragments=[
            fragment("a", start=0, end=3, text="甲乙丙"),
            fragment("b", start=2, end=4, text="丙丁"),
        ])
        with self.assertRaises(ValueError):
            process("narration-text", data)

    def test_text_length_must_match_position_range(self):
        data = export(fragments=[fragment("a", start=0, end=3, text="甲乙")])
        with self.assertRaises(ValueError):
            process("narration-language", data)

    def test_declaration_level_is_checked(self):
        data = export(
            fragments=[fragment("a", start=0, end=1, text="甲")],
            language_declarations=[declaration("d", "word", 0, 1, "en")],
        )
        with self.assertRaises(ValueError):
            process("narration-language", data)


if __name__ == "__main__":
    unittest.main()
