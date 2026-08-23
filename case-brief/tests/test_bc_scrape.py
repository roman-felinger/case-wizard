"""Unit tests for lib/bc_scrape.py's logic that doesn't require a real
Chrome/CDP connection or a live Business Central session. Like
test_crm_scrape.py, this fakes only the narrow interface the module actually
calls on a page/frame (`.frames`, `.evaluate()`, `.title()`, `.url`) rather
than mocking Playwright itself -- the module's own multi-frame
best-of/fallback logic is real and worth locking in given the module's own
docstring says BC's DOM is still "trickier" than CRM/ADO's (iframes, labels
landing on non-<input> elements) and a wrong selector guess should degrade
to a raw-text dump rather than silently return nothing.

Covers:
  - `find_bc_tabs`' host filtering.
  - `extract` picking the frame with the most extracted pairs/most text
    across however many frames a page has (a wrong/empty top frame must not
    hide data actually found in an iframe).
  - The raw-text fallback firing only when no labeled fields were found.
  - The 40-field cap.
  - One frame's `.evaluate()` raising not aborting extraction from the
    others.

Not covered: `_EXTRACT_JS` itself (opaque JS text from Python's point of
view) and running any of this against a real, rendered Business Central
page -- both need Playwright + a live BC tab, and per TODO.md the selector
itself is still unverified against real BC output.

Run with: python -m unittest discover -s tests -v   (from case-brief/)
      or: python -m pytest tests                     (if pytest is installed)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import bc_scrape


class FakeFrame:
    def __init__(self, result=None, error=None):
        self._result = result if result is not None else {}
        self._error = error

    def evaluate(self, js):
        if self._error is not None:
            raise self._error
        return self._result


class FakePage:
    def __init__(self, url, frames, title=""):
        self.url = url
        self.frames = frames
        self._title = title

    def title(self):
        return self._title


class FindBcTabsTests(unittest.TestCase):
    def test_filters_by_host_substring(self):
        pages = [FakePage("https://x.businesscentral.dynamics.com/y", []), FakePage("https://other.example.com", [])]
        result = bc_scrape.find_bc_tabs(pages)
        self.assertEqual(result, [pages[0]])

    def test_respects_a_custom_host(self):
        pages = [FakePage("https://bc.mycompany.example.com/", [])]
        self.assertEqual(bc_scrape.find_bc_tabs(pages, host="mycompany.example.com"), pages)
        self.assertEqual(bc_scrape.find_bc_tabs(pages, host="businesscentral.dynamics.com"), [])


class ExtractTests(unittest.TestCase):
    def test_picks_the_frame_with_more_pairs_over_an_emptier_top_frame(self):
        top_frame = FakeFrame({"title": "BC", "pairs": [], "text": ""})
        iframe = FakeFrame({"title": None, "pairs": [["No.", "103042"], ["Customer Name", "Contoso"]], "text": "irrelevant shorter text"})
        page = FakePage("https://bc/card", [top_frame, iframe], title="BC fallback title")
        result = bc_scrape.extract(page)
        self.assertEqual(len(result["fields"]), 2)
        self.assertEqual(result["fields"][0], {"label": "No.", "value": "103042"})

    def test_title_falls_back_to_page_title_when_no_frame_provides_one(self):
        frame = FakeFrame({"title": None, "pairs": [], "text": ""})
        page = FakePage("https://bc/card", [frame], title="Fallback Title")
        result = bc_scrape.extract(page)
        self.assertEqual(result["page_title"], "Fallback Title")

    def test_raw_text_fallback_used_only_when_no_fields_were_found(self):
        frame = FakeFrame({"title": "BC", "pairs": [], "text": "visible page text dump"})
        page = FakePage("https://bc/card", [frame])
        result = bc_scrape.extract(page)
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["raw_text"], "visible page text dump")

    def test_raw_text_is_none_when_fields_were_found(self):
        frame = FakeFrame({"title": "BC", "pairs": [["No.", "1"]], "text": "some text"})
        page = FakePage("https://bc/card", [frame])
        result = bc_scrape.extract(page)
        self.assertIsNotNone(result["fields"])
        self.assertIsNone(result["raw_text"])

    def test_fields_are_capped_at_forty(self):
        pairs = [[f"Label{i}", f"Value{i}"] for i in range(60)]
        frame = FakeFrame({"title": "BC", "pairs": pairs, "text": ""})
        page = FakePage("https://bc/card", [frame])
        result = bc_scrape.extract(page)
        self.assertEqual(len(result["fields"]), 40)

    def test_a_frame_raising_during_evaluate_is_skipped_not_fatal(self):
        broken_frame = FakeFrame(error=RuntimeError("frame detached"))
        good_frame = FakeFrame({"title": "BC", "pairs": [["No.", "1"]], "text": "t"})
        page = FakePage("https://bc/card", [broken_frame, good_frame])
        result = bc_scrape.extract(page)
        self.assertEqual(result["fields"], [{"label": "No.", "value": "1"}])

    def test_no_frames_at_all_returns_an_empty_but_well_formed_result(self):
        page = FakePage("https://bc/card", [], title="Empty Page")
        result = bc_scrape.extract(page)
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["page_title"], "Empty Page")
        self.assertEqual(result["url"], "https://bc/card")


if __name__ == "__main__":
    unittest.main()
