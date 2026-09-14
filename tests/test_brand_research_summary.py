import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.brand_keyword_research import summary


class SummaryTests(unittest.TestCase):
    def fixture(self, statuses=('VALID', 'VALID', 'VALID', 'PARTIAL')):
        inventory = [dict(store_code=str(i), place_id=str(i), store_name='매장'+str(i),
                          status='ELIGIBLE' if i < 4 else 'MISSING_PLACE_ID') for i in range(5)]
        candidate = dict(candidate_id='a', query='설렁탕', volume_status='EXACT',
                         volume_total=100, volume_pc=40, volume_mobile=60)
        rows = [dict(candidate_id='a', query='설렁탕', place_id=str(i),
                     rank_status=status, own_rank=rank, volume_total=100)
                for i, (status, rank) in enumerate(zip(statuses, [2, 15, None, 1]))]
        return {'inventory': inventory, 'config': {'targets': inventory[:4]}}, {'candidates': [candidate], 'rows': rows}

    def test_population_and_volume(self):
        state, result = self.fixture()
        s = summary.summarize(state, result)[0]
        self.assertEqual([s[k] for k in ('total_stores','eligible_stores','valid_stores','unknown_stores')], [5,4,3,2])
        self.assertEqual(s['coverage_pct'], 60)
        self.assertAlmostEqual(s['top10_rate_pct'], 100/3)
        self.assertAlmostEqual(s['top20_rate_pct'], 200/3)
        self.assertEqual(s['confirmed_top20_pct_all'], 40)
        self.assertEqual(s['rank_bands'], dict(top3=1, rank4_10=0, rank11_20=1, not_in_top20=1, unknown=2))
        self.assertEqual(s['mean_rank_top20'], 8.5)
        self.assertEqual(s['median_rank_top20'], 8.5)
        self.assertEqual((s['volume_total'], s['volume_pc'], s['volume_mobile']), (100,40,60))

    def test_stale_missing_and_rank21(self):
        state, result = self.fixture(('VALID','STALE','MISSING','PARTIAL'))
        result['rows'][0]['own_rank'] = 21
        s = summary.summarize(state,result)[0]
        self.assertEqual((s['valid_stores'],s['top20_count'],s['unknown_stores']), (1,0,4))
        self.assertEqual(s['rank_status_counts']['STALE'],1)
        self.assertIsNone(s['mean_rank_top20'])

    def test_no_eligible_and_zero_population(self):
        state,result = self.fixture()
        state['inventory'] = [dict(status='MISSING_PLACE_ID')]
        state['config']['targets'] = []
        result['rows'] = []
        s = summary.summarize(state,result)[0]
        self.assertEqual((s['total_stores'], s['eligible_stores'], s['unknown_stores']), (1,0,1))
        self.assertIsNone(s['top10_rate_pct'])
        del state['inventory']
        self.assertIsNone(summary.summarize(state,result)[0]['coverage_pct'])

    def test_invalid_rank_is_unknown_and_config_population(self):
        for rank in (0,-1,True,'2',1.5):
            state,result = self.fixture()
            del state['inventory']
            result['rows'][0]['own_rank'] = rank
            s = summary.summarize(state,result)[0]
            self.assertEqual((s['total_stores'],s['valid_stores']), (4,2))

    def test_csv_and_markdown(self):
        state,result = self.fixture()
        result['candidates'][0]['query'] = '=SUM(1,2)'
        result['rows'][0]['store_name'] = '\t=1+1'
        state['inventory'][0]['store_name'] = '  @공격'
        summaries = summary.summarize(state,result)
        with tempfile.TemporaryDirectory() as tmp:
            summary.write_csvs(Path(tmp),state,result,summaries)
            for name,field in [('keyword-summary.csv','query'),('store-ranks.csv','store_name'),('store-inventory.csv','store_name')]:
                p = Path(tmp)/name
                self.assertTrue(p.read_bytes().startswith(b'\xef\xbb\xbf'))
                with p.open(encoding='utf-8-sig',newline='') as f:
                    row = next(csv.DictReader(f))
                self.assertTrue(row[field].startswith("'"))
            with (Path(tmp)/'keyword-summary.csv').open(encoding='utf-8-sig',newline='') as f:
                self.assertEqual(next(csv.DictReader(f))['volume_total'],'100')
        md = summary.summary_markdown(summaries)
        self.assertIn('전국', md)
        self.assertIn('유효 관측 매장', md)
        self.assertIn('미확인', md)

    def test_csv_canonical_replay_is_identical(self):
        state, result = self.fixture()
        summaries = summary.summarize(state, result)
        with tempfile.TemporaryDirectory() as tmp:
            original, replay = Path(tmp)/'original', Path(tmp)/'replay'
            summary.write_csvs(original, state, result, summaries)
            canonical = lambda value: json.loads(json.dumps(value, sort_keys=True))
            summary.write_csvs(replay, canonical(state), canonical(result), canonical(summaries))
            for path in original.iterdir():
                self.assertEqual(path.read_bytes(), (replay/path.name).read_bytes())

    def test_markdown_table_column_counts_match(self):
        state, result = self.fixture()
        lines = summary.summary_markdown(summary.summarize(state,result)).splitlines()
        table = [line for line in lines if line.startswith('|')]
        self.assertEqual(len(set(line.count('|') for line in table)), 1)


if __name__ == '__main__':
    unittest.main()
