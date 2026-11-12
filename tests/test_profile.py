import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import stats


class CalendarTests(unittest.TestCase):
    def test_snapshot_preview_excludes_future_contribution_days(self):
        days = {'2026-01-01': 2, '2026-01-02': 1, '2026-01-03': 99,
                '2026-01-04': 99, '2026-01-05': 99}
        current, longest = stats.streaks(days, date(2026, 1, 2))
        self.assertEqual(current.length, 2)
        self.assertEqual(longest.length, 2)
        raw = {'login':'example','createdAt':'2025-01-01T00:00:00Z','days':days,
               'commits':4,'pullRequests':0,'issues':0,'publicRepos':0,'repos':[], 'followers':0}
        self.assertEqual(stats.summarize(raw, {}, date(2026,1,2)).contributions, 3)

    def test_today_can_be_empty_and_gaps_break_streaks(self):
        current, longest = stats.streaks({'2026-01-01':1,'2026-01-03':1}, date(2026,1,4))
        self.assertEqual((current.length, longest.length), (1,1))
        self.assertEqual(stats.streaks({}, date(2026,1,4))[0].length,0)


class PreviewTests(unittest.TestCase):
    def test_check_writes_nothing_and_build_outputs_valid_svg(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            out = Path(temporary) / 'preview'
            build.main(['--output-dir', str(out), '--check'])
            self.assertFalse(out.exists())
            build.main(['--output-dir', str(out)])
            self.assertEqual(len(list(out.glob('*.svg'))), 4)
            for path in out.glob('*.svg'):
                self.assertEqual(ET.parse(path).getroot().tag, '{http://www.w3.org/2000/svg}svg')
            self.assertFalse(list(out.glob('.profile-*')))

    def test_invalid_last_card_does_not_replace_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            out = Path(temporary)
            sentinel = out / 'header-light.svg'
            sentinel.write_text('keep this')
            with patch.object(build.cards, 'stack', return_value='<broken'):
                with self.assertRaises(ET.ParseError):
                    build.main(['--output-dir', str(out)])
            self.assertEqual(sentinel.read_text(),'keep this')
            self.assertEqual(len(list(out.iterdir())),1)

    def test_activity_can_be_checked_from_fixture_without_network(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            fixture = root / 'data.json'
            fixture.write_text(json.dumps({'login':'example','createdAt':'2025-01-01T00:00:00Z',
                'days':{'2026-01-01':1},'commits':1,'pullRequests':0,'issues':0,
                'publicRepos':0,'repos':[],'followers':0}))
            with patch.object(build.stats,'fetch',side_effect=AssertionError('Network forbidden')):
                build.main(['--data',str(fixture),'--today','2026-01-01','--check',
                            '--output-dir',str(root/'preview')])
            self.assertFalse((root/'preview').exists())


if __name__ == '__main__':
    unittest.main()
