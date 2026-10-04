import unittest

import pytest_bazel

from devinfra.ci.skills.ci_latency.scripts import attribution as a
from devinfra.ci.skills.ci_latency.scripts import publish as p


class AttributionTests(unittest.TestCase):
    def test_shared_setup_and_overlapping_triggers(self):
        result = a.calculate({'resource': 'runner-seconds', 'runs': [{'id': 'run-1', 'source_commit': 'sha', 'units': [
            {'name': 'provision', 'kind': 'provision', 'seconds': 90, 'triggers': ['a', 'b']},
            {'name': 'test', 'kind': 'test', 'seconds': 30, 'triggers': ['b', 'c']},
        ]}]})
        self.assertEqual(result['measured_seconds'], 120)
        self.assertEqual({x['trigger']: x['seconds'] for x in result['attribution']}, {'a': 45, 'b': 60, 'c': 15})

    def test_bad_values(self):
        for triggers, seconds in [([], 3), (['a', 'a'], 3), (['a'], -1), (['a'], float('nan'))]:
            with self.subTest(triggers=triggers, seconds=seconds), self.assertRaises(ValueError):
                a.calculate({'resource': 'worker-seconds', 'runs': [{'id': 'x', 'source_commit': 'sha',
                    'units': [{'name': 'u', 'kind': 'test', 'seconds': seconds, 'triggers': triggers}]}]})

    def test_html_escapes(self):
        self.assertIn('&lt;script&gt;', p.render('<script>'))
        self.assertNotIn('<script>', p.render('<script>'))


if __name__ == '__main__':
    pytest_bazel.main()
