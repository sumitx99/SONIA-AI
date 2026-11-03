import unittest

from app.services.parsing.pdf_utils import chunk_text


class SectionChunkingTests(unittest.TestCase):
    def test_sibling_sections_keep_their_own_heading_paths(self):
        chunks = chunk_text(
            "# Handbook\n## Leave\n### Annual\nAnnual allowance.\n"
            "### Sick\nMedical allowance.\n## Hours\nWorking hours.\n"
        )
        self.assertEqual(chunks, [
            "Section: Handbook > Leave > Annual\n\nAnnual allowance.",
            "Section: Handbook > Leave > Sick\n\nMedical allowance.",
            "Section: Handbook > Hours\n\nWorking hours.",
        ])

    def test_long_section_overlaps_without_crossing_section_boundary(self):
        body = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        chunks = chunk_text(
            f"# Guide\n## Alpha\n{body}\n## Beta\nUnrelated content.",
            chunk_size=40, chunk_overlap=10,
        )
        prefix = "Section: Guide > Alpha\n\n"
        first, second = [chunk.removeprefix(prefix) for chunk in chunks[:2]]
        self.assertEqual(first[-10:], second[:10])
        self.assertTrue(all(chunk.startswith(prefix) for chunk in chunks[:2]))
        self.assertLessEqual(len(first), 40)
        self.assertLessEqual(len(second), 40)
        self.assertEqual(chunks[2], "Section: Guide > Beta\n\nUnrelated content.")
        self.assertEqual(first + second[10:], body)

    def test_preamble_is_preserved_without_an_unrelated_heading(self):
        self.assertEqual(chunk_text("Introduction.\n\n# Policy\nPolicy text."), [
            "Introduction.", "Section: Policy\n\nPolicy text.",
        ])

    def test_plain_text_fallback_preserves_content_and_overlap(self):
        text = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        chunks = chunk_text(text, chunk_size=40, chunk_overlap=10)
        self.assertEqual(chunks[0] + chunks[1][10:], text)
        self.assertEqual(chunks[0][-10:], chunks[1][:10])
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))

    def test_setext_headings_and_closing_atx_markers(self):
        self.assertEqual(chunk_text(
            "Handbook\n========\nLeave\n-----\nAllowance.\n## Hours ##\nNine to six."
        ), [
            "Section: Handbook > Leave\n\nAllowance.",
            "Section: Handbook > Hours\n\nNine to six.",
        ])

    def test_fenced_code_does_not_create_or_close_sections(self):
        for marker in ("```", "~~~~"):
            with self.subTest(marker=marker):
                code = f"{marker}python\n# Not a section\nLabel\n---\n``\n{marker}"
                chunks = chunk_text(f"# Guide\n{code}\n## Real\nReal content.")
                self.assertEqual(chunks[0], f"Section: Guide\n\n{code}")
                self.assertEqual(chunks[1], "Section: Guide > Real\n\nReal content.")

    def test_heading_only_document_and_empty_input(self):
        self.assertEqual(chunk_text("# Handbook\n## Leave"), [
            "Section: Handbook > Leave",
        ])
        self.assertEqual(chunk_text("  \n\n"), [])

    def test_invalid_sizes_fail_clearly(self):
        for size, overlap in ((0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)):
            with self.subTest(size=size, overlap=overlap):
                with self.assertRaises(ValueError):
                    chunk_text("content", size, overlap)


if __name__ == "__main__":
    unittest.main()
