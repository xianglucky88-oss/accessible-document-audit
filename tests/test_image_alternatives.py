import json
from pathlib import Path
import unittest

from accessible_document_audit import process
from accessible_document_audit.image_alternatives import build_facts

ROOT = Path(__file__).resolve().parent.parent

BASE = {
    "published_languages": ["zh-Hans", "en"],
    "texts": [
        {"id": "t-route", "language": "zh-Hans", "content": "沿北侧通道直行。", "covers": ["route"]},
        {"id": "t-exit", "language": "zh-Hans", "content": "由三号出口离开。", "covers": ["exit-a"]},
        {"id": "t-en-route", "language": "en", "content": "Go straight.", "covers": ["route"]},
        {"id": "t-en-exit", "language": "en", "content": "Leave by exit 3.", "covers": ["exit-a"]},
    ],
    "descriptions": [
        {"id": "d-zh", "language": "zh-Hans", "text_ids": ["t-route", "t-exit"]},
        {"id": "d-en", "language": "en", "translation_of": "d-zh", "text_ids": ["t-en-route", "t-en-exit"]},
    ],
    "records": [],
}


def figure(**overrides):
    record = {
        "id": "fig-1",
        "page": 2,
        "object": "figure-1",
        "purpose": "wayfinding",
        "placement": "body",
        "required_items": ["route", "exit-a"],
        "description_ids": ["d-zh"],
    }
    record.update(overrides)
    return record


def run(**overrides):
    data = json.loads(json.dumps(BASE))
    data.update(overrides)
    return build_facts(data)


def fact(facts, language="zh-Hans"):
    matches = [row for row in facts if row["language"] == language]
    assert len(matches) == 1, matches
    return matches[0]


class ImageAlternativeTests(unittest.TestCase):
    def test_reports_one_fact_per_published_language(self):
        facts = run(records=[figure()])
        self.assertEqual([row["fact_id"] for row in facts], ["fig-1@en", "fig-1@zh-Hans"])
        for language in ("zh-Hans", "en"):
            row = fact(facts, language)
            self.assertEqual(row["covered_items"], ["route", "exit-a"])
            self.assertEqual(row["missing_items"], [])
            self.assertEqual(row["status"], "verified")
            self.assertEqual(row["placement"], "body")
            self.assertEqual(row["purpose"], "wayfinding")

    def test_partial_coverage_does_not_count_as_replaced(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"][0]["text_ids"] = ["t-exit"]
        facts = run(descriptions=data["descriptions"], records=[figure()])
        row = fact(facts, "zh-Hans")
        self.assertEqual(row["covered_items"], ["exit-a"])
        self.assertEqual(row["missing_items"], ["route"])
        self.assertEqual(row["status"], "needs_supplement")

    def test_union_of_multiple_text_segments(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"].append(
            {"id": "d-zh-parts", "language": "zh-Hans", "text_ids": ["t-route", "t-exit"]})
        facts = run(descriptions=data["descriptions"],
                    records=[figure(description_ids=["d-zh-parts"], published_languages=["zh-Hans"])])
        self.assertEqual(fact(facts)["status"], "verified")

    def test_one_description_shared_by_several_figures(self):
        facts = run(records=[
            figure(),
            figure(id="fig-2", page=4, object="figure-2", published_languages=["zh-Hans"]),
        ])
        shared = [row for row in facts if row["description_ids"] == ["d-zh"]]
        self.assertEqual({row["fact_id"] for row in shared}, {"fig-1@en", "fig-1@zh-Hans", "fig-2@zh-Hans"})
        self.assertTrue(all(row["status"] == "verified" for row in shared))

    def test_nested_description_refines_coverage(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"].append(
            {"id": "d-zh-box", "language": "zh-Hans", "includes": ["d-zh"]})
        facts = run(descriptions=data["descriptions"],
                    records=[figure(description_ids=["d-zh-box"], published_languages=["zh-Hans"])])
        self.assertEqual(fact(facts)["covered_items"], ["route", "exit-a"])

    def test_missing_translation_is_not_inherited(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"] = data["descriptions"][:1]
        facts = run(descriptions=data["descriptions"], records=[figure()])
        row = fact(facts, "en")
        self.assertEqual(row["covered_items"], [])
        self.assertEqual(row["missing_items"], ["route", "exit-a"])
        self.assertEqual(row["missing_translations"],
                         [{"description": "d-zh", "language": "en", "through": None}])
        self.assertEqual(row["status"], "needs_supplement")
        self.assertEqual(fact(facts, "zh-Hans")["status"], "verified")

    def test_corrected_exit_requires_supplement_but_unrelated_figure_stays_verified(self):
        data = json.loads(json.dumps(BASE))
        data["texts"].append({"id": "t-fixed", "language": "zh-Hans",
                              "content": "三号出口已封闭，改由四号出口离开。", "covers": ["route", "exit-b"]})
        data["descriptions"].append({
            "id": "d-zh-fixed", "language": "zh-Hans",
            "text_ids": ["t-fixed"], "corrections": ["exit-a"],
        })
        facts = run(texts=data["texts"], descriptions=data["descriptions"], records=[
            figure(description_ids=["d-zh-fixed"], published_languages=["zh-Hans"]),
            figure(id="fig-route-only", page=5, object="figure-5", required_items=["route"],
                   description_ids=["d-zh-fixed"], published_languages=["zh-Hans"]),
        ])
        changed = fact([row for row in facts if row["fact_id"].startswith("fig-1")])
        self.assertEqual(changed["corrected_items"], ["exit-a"])
        self.assertEqual(changed["missing_items"], ["exit-a"])
        self.assertEqual(changed["status"], "needs_supplement")
        untouched = fact([row for row in facts if row["fact_id"].startswith("fig-route-only")])
        self.assertEqual(untouched["required_items"], ["route"])
        self.assertEqual(untouched["status"], "verified")

    def test_cycle_keeps_confirmable_coverage_and_records_gap(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"] += [
            {"id": "d-a", "language": "zh-Hans", "text_ids": ["t-route"], "includes": ["d-b"]},
            {"id": "d-b", "language": "zh-Hans", "includes": ["d-a"]},
        ]
        facts = run(descriptions=data["descriptions"], records=[
            figure(description_ids=["d-a"], published_languages=["zh-Hans"])])
        row = fact(facts)
        self.assertEqual(row["covered_items"], ["route"])
        self.assertEqual(row["missing_items"], ["exit-a"])
        self.assertEqual(row["unresolved_references"], [{"kind": "cycle", "id": "d-a", "through": "d-b"}])
        self.assertEqual(row["status"], "needs_supplement")

    def test_reference_to_deleted_text_keeps_other_segments(self):
        data = json.loads(json.dumps(BASE))
        data["descriptions"][0]["text_ids"] = ["t-route", "t-deleted"]
        facts = run(descriptions=data["descriptions"],
                    records=[figure(published_languages=["zh-Hans"])])
        row = fact(facts)
        self.assertEqual(row["covered_items"], ["route"])
        self.assertEqual(row["unresolved_references"],
                         [{"kind": "text", "id": "t-deleted", "through": "d-zh"}])

    def test_reference_to_removed_description_is_reported(self):
        facts = run(records=[figure(description_ids=["d-removed"], published_languages=["zh-Hans"])])
        row = fact(facts)
        self.assertEqual(row["unresolved_references"],
                         [{"kind": "description", "id": "d-removed", "through": None}])

    def test_decoration_figure_has_no_required_route(self):
        facts = run(records=[figure(id="crop", page=9, object="crop-1", purpose="decoration",
                                    placement="chapter-decoration", required_items=[],
                                    description_ids=["d-zh"])])
        for row in facts:
            self.assertEqual(row["required_items"], [])
            self.assertEqual(row["status"], "verified")
            self.assertEqual(row["placement"], "chapter-decoration")

    def test_rejects_invalid_material_and_records(self):
        with self.assertRaisesRegex(ValueError, "purpose"):
            run(records=[figure(purpose="illustration")])
        with self.assertRaisesRegex(ValueError, "required_items"):
            run(records=[figure(required_items=[])])
        with self.assertRaisesRegex(ValueError, "decoration figure"):
            run(records=[figure(purpose="decoration", placement="chapter-decoration")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            data = json.loads(json.dumps(BASE))
            data["descriptions"].append({"id": "d-zh", "language": "zh-Hans"})
            run(descriptions=data["descriptions"])
        with self.assertRaisesRegex(ValueError, "translation"):
            data = json.loads(json.dumps(BASE))
            data["descriptions"].append(
                {"id": "d-en-2", "language": "en", "translation_of": "d-zh"})
            run(descriptions=data["descriptions"])
        with self.assertRaisesRegex(ValueError, "language"):
            data = json.loads(json.dumps(BASE))
            data["descriptions"][0]["text_ids"] = ["t-en-route"]
            run(descriptions=data["descriptions"])

    def test_process_entry_uses_same_pipeline(self):
        data = json.loads(json.dumps(BASE))
        data["records"] = [figure()]
        self.assertEqual(process("image-alternatives", data), build_facts(data))

    def test_the_corpus_covers_every_stated_rule(self):
        data = json.loads((ROOT / "examples" / "image-alternatives.json").read_text(encoding="utf-8"))
        facts = {row["fact_id"]: row for row in build_facts(data)}
        # 同一说明被多幅图引用；部分覆盖不能算整张图已替代。
        self.assertEqual(facts["fig-floor3-body@zh-Hans"]["status"], "verified")
        self.assertEqual(facts["fig-floor5-body@zh-Hans"]["missing_items"], ["route"])
        # 多段文字共同提供的说明可以覆盖全部必要项。
        self.assertEqual(facts["fig-floor4-body@zh-Hans"]["status"], "verified")
        # 外语译文没交齐：同一图在 en 下不能沿用 zh-Hans 的完成状态。
        self.assertEqual(facts["fig-floor10-body@zh-Hans"]["status"], "verified")
        self.assertEqual(facts["fig-floor10-body@en"]["status"], "needs_supplement")
        self.assertEqual(facts["fig-floor10-body@en"]["missing_translations"][0]["language"], "en")
        # 更正出口后，需要补充说明的正文图与内容无关的已核验图分别列出。
        self.assertEqual(facts["fig-floor6-body@zh-Hans"]["corrected_items"], ["exit-a"])
        self.assertEqual(facts["fig-floor6-body@zh-Hans"]["status"], "needs_supplement")
        self.assertEqual(facts["fig-floor7-body@zh-Hans"]["status"], "verified")
        # 嵌套引用不闭合或指向已删内容时保留可确认内容并登记缺口。
        damaged = facts["fig-floor11-body@zh-Hans"]
        self.assertEqual(damaged["covered_items"], ["route"])
        self.assertEqual(damaged["unresolved_references"][0]["kind"], "text")
        looped = facts["fig-floor12-body@zh-Hans"]
        self.assertEqual(looped["covered_items"], ["route"])
        self.assertEqual(looped["unresolved_references"][0]["kind"], "cycle")
        # 正文图与章节装饰图按出现位置分别复核。
        self.assertEqual(facts["fig-floor8-decoration@zh-Hans"]["placement"], "chapter-decoration")
        self.assertEqual(facts["fig-floor8-decoration@zh-Hans"]["status"], "verified")


if __name__ == "__main__":
    unittest.main()
