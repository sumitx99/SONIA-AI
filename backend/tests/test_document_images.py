import unittest

import pymupdf

from app.services.images.document_images import extract_document_images, requested_image_location, wants_images


def sample_pdf(repeated=False, rotation=0):
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((30, 35), "System Guide")
    page.insert_text((30, 85), "Before: requests enter the API.")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 20, 20), False)
    pixmap.clear_with(128)
    xref = page.insert_image(pymupdf.Rect(30, 120, 150, 200),
                             stream=pixmap.tobytes("png"), keep_proportion=False)
    page.insert_text((30, 240), "After: the worker processes the queue.")
    if repeated:
        page.insert_image(pymupdf.Rect(30, 290, 150, 370), xref=xref, keep_proportion=False)
        page.insert_text((30, 410), "After the second image.")
    page.set_rotation(rotation)
    data = document.tobytes()
    document.close()
    return data


class ImageExtractionTests(unittest.TestCase):
    def test_source_location_surrounding_text_and_heading_are_preserved(self):
        images = extract_document_images(sample_pdf(), "# System Guide\nBefore: requests enter the API.")
        self.assertEqual(len(images), 1)
        image = images[0]
        self.assertEqual(image["page_number"], 1)
        self.assertEqual(image["image_number"], 1)
        self.assertEqual(image["bbox"], [30.0, 120.0, 150.0, 200.0])
        self.assertEqual(image["heading_path"], ["System Guide"])
        self.assertIn("requests enter the API", image["text_before"])
        self.assertIn("worker processes the queue", image["text_after"])
        self.assertEqual(image["before_context"][-1]["page_number"], 1)
        self.assertEqual(image["after_context"][0]["page_number"], 1)
        self.assertEqual((image["width"], image["height"]), (240, 160))
        self.assertTrue(image["data"].startswith(b"\x89PNG"))
        self.assertIn("requests enter the API", image["search_text"])

    def test_repeated_asset_keeps_distinct_occurrences(self):
        first, second = extract_document_images(sample_pdf(repeated=True))
        self.assertNotEqual(first["image_id"], second["image_id"])
        self.assertNotEqual(first["bbox"], second["bbox"])
        self.assertEqual([first["image_number"], second["image_number"]], [1, 2])
        self.assertIn("After the second image", second["text_after"])

    def test_rotated_page_keeps_unrotated_location_and_visible_crop(self):
        image = extract_document_images(sample_pdf(rotation=90))[0]
        self.assertEqual(image["page_rotation"], 90)
        self.assertEqual(image["bbox"], [30.0, 120.0, 150.0, 200.0])
        self.assertEqual((image["width"], image["height"]), (160, 240))

    def test_surrounding_text_can_cross_page_boundary_with_source_locations(self):
        document = pymupdf.open()
        document.new_page().insert_text((30, 40), "Previous page explanation.")
        page = document.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 10, 10), False)
        pixmap.clear_with(128)
        page.insert_image(pymupdf.Rect(30, 30, 100, 100), stream=pixmap.tobytes("png"))
        page.insert_text((30, 140), "Following explanation.")
        image = extract_document_images(document.tobytes())[0]
        document.close()
        self.assertEqual(image["page_number"], 2)
        self.assertEqual(image["before_context"][0]["page_number"], 1)
        self.assertEqual(image["after_context"][0]["page_number"], 2)

    def test_text_only_document_has_no_images(self):
        document = pymupdf.open()
        document.new_page().insert_text((30, 40), "Only text.")
        self.assertEqual(extract_document_images(document.tobytes()), [])
        document.close()

    def test_explicit_requests_and_locations_in_english_and_hinglish(self):
        cases = [
            ("Show image 2 on page 12", (12, 2)),
            ("page 12 ki second image dikhao", (12, 2)),
            ("12 page ki dusri image", (12, 2)),
            ("पेज १२ की दूसरी तस्वीर", (12, 2)),
            ("show 3rd image on pg. 8", (8, 3)),
            ("API wala diagram dikhao", (None, None)),
        ]
        for query, location in cases:
            with self.subTest(query=query):
                self.assertTrue(wants_images(query))
                self.assertEqual(requested_image_location(query), location)
        self.assertFalse(wants_images("Summarize employee leave policy"))
        self.assertFalse(wants_images("How does imagination work?"))


if __name__ == "__main__":
    unittest.main()
