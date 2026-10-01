import unittest

from scripts.import_buildcores import transform


class BuildcoresTests(unittest.TestCase):
    def setUp(self):
        self.uid = '007a5a23-1e12-45b7-90d0-565b80876539'

    def test_preserves_source_and_curated_fields(self):
        data = {'opendb_id': self.uid, 'metadata': {'name': 'x' * 210}, 'custom': {'unknown': [1, 2]}}
        row, warnings = transform(data, 'CPU', self.uid, 'abc', '2026-09-29T00:00:00Z')
        self.assertEqual(row['specs'], data)
        self.assertEqual(len(row['name']), 200)
        self.assertEqual(row['manufacturer'], 'Unknown')
        self.assertEqual(row['external_id'], 'buildcores:CPU:' + self.uid)
        self.assertTrue(warnings)
        for field in ('lowest_price', 'image_url', 'description', 'is_active'):
            self.assertNotIn(field, row)

    def test_mismatched_id_rejected(self):
        with self.assertRaises(ValueError):
            transform({'opendb_id': self.uid}, 'CPU', 'wrong', 'abc', '')

    def test_unmapped_category_rejected(self):
        with self.assertRaises(ValueError):
            transform({'opendb_id': self.uid}, 'FutureCategory', self.uid, 'abc', '')

    def test_repeat_transform_has_same_identity(self):
        data = {'opendb_id': self.uid, 'metadata': {'name': 'CPU'}}
        first, _ = transform(data, 'CPU', self.uid, 'first', '')
        second, _ = transform(data, 'CPU', self.uid, 'second', '')
        self.assertEqual(first['external_id'], second['external_id'])

    def test_same_uuid_in_different_categories_is_preserved(self):
        data = {'opendb_id': self.uid}
        first, _ = transform(data, 'CPU', self.uid, 'abc', '')
        second, _ = transform(data, 'CPUCooler', self.uid, 'abc', '')
        self.assertNotEqual(first['external_id'], second['external_id'])


if __name__ == '__main__':
    unittest.main()
