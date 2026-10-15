"""Agent 栏目的隔离、过滤、重跑和搜索回归测试（无网络）。"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from techstation import github, run, store
from techstation.config import Config, REPO_ROOT
from techstation.scoring import KeywordScorer, build_profile


class AgentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, path in {
            'PAPERS_DIR': root / 'papers', 'REPOS_DIR': root / 'repos',
            'AGENTS_DIR': root / 'agents', 'REPO_SNAPSHOT_PATH': root / 'repos-seen.json',
            'AGENT_SNAPSHOT_PATH': root / 'agents-seen.json', 'SEARCH_INDEX_PATH': root / 'search-index.json',
        }.items():
            p = patch.object(store, name, path)
            p.start()
            self.addCleanup(p.stop)
        self.cfg = Config.load(REPO_ROOT / 'profile' / 'agents.yaml')
        self.profile = build_profile(self.cfg, [], None)
        self.kw = KeywordScorer(self.cfg.boost_keywords, self.cfg.mute_keywords)
        self.day = date.today().isoformat()
        self.args = SimpleNamespace(skip_media=True)

    def repo(self, name='coding-agent', license='MIT', stars=1000):
        return github.Repo(
            id=f'team/{name}', name=name, full_name=f'team/{name}',
            description='LLM coding agent with tool calling', url=f'https://github.com/team/{name}',
            homepage='', stars=stars, forks=20, language='Python', topics=['ai-agents'],
            created_at=f'{self.day}T00:00:00Z', pushed_at=f'{self.day}T00:00:00Z', license=license,
        )

    def execute(self, repos):
        with patch.object(github, 'fetch_repos', return_value=repos):
            return run.run_repos(self.cfg, self.day, self.profile, None, self.kw, self.args, kind='agents')

    def test_filter_and_storage_isolation(self):
        store.write_daily('repos', self.day, [{'id': 'robot/existing'}], {})
        before = store.read_daily('repos', self.day)
        self.assertEqual(self.execute([self.repo(), self.repo('no-license', ''), self.repo('awesome-agents')]), 1)
        self.assertEqual(store.read_daily('repos', self.day), before)
        self.assertEqual(store.load_repo_snapshot(), {})
        self.assertIn('team/coding-agent', store.load_repo_snapshot('agents'))
        self.assertEqual(store.read_daily('agents', self.day)['items'][0]['rank'], 1)

    def test_robot_channel_retains_existing_behavior(self):
        self.execute([self.repo()])
        before = store.read_daily('agents', self.day)
        with patch.object(github, 'fetch_repos', return_value=[self.repo('robot', '')]):
            count = run.run_repos(self.cfg, self.day, self.profile, None, self.kw, self.args)
        self.assertEqual(count, 1)
        self.assertEqual(store.read_daily('agents', self.day), before)
        self.assertEqual(store.read_daily('repos', self.day)['items'][0]['id'], 'team/robot')

    def test_empty_fetch_preserves_previous_data(self):
        self.execute([self.repo()])
        before = store.read_daily('agents', self.day)
        snapshot = store.load_repo_snapshot('agents')
        self.assertEqual(self.execute([]), 0)
        self.assertEqual(store.read_daily('agents', self.day), before)
        self.assertEqual(store.load_repo_snapshot('agents'), snapshot)

    def test_same_day_star_delta_stable(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.save_repo_snapshot({'team/coding-agent': {'stars': 900, 'date': yesterday, 'first_seen': yesterday}}, 120, 'agents')
        self.execute([self.repo()])
        self.execute([self.repo()])
        self.assertEqual(store.read_daily('agents', self.day)['items'][0]['stars_delta'], 100)

    def test_search_uses_latest_repo_across_both_channels(self):
        self.execute([self.repo()])
        old = self.repo(stars=500).to_dict()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        store.write_daily('repos', yesterday, [old], {})
        store.rebuild_search_index(120)
        items = store.read_json(store.SEARCH_INDEX_PATH, {})['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['stars'], 1000)
        self.assertEqual(items[0]['t'], 'repo')

    def test_agent_pruning_does_not_delete_robot_data(self):
        old = (date.today() - timedelta(days=130)).isoformat()
        store.write_daily('repos', old, [], {})
        store.write_daily('agents', old, [], {})
        store.prune_daily_files('agents', 120)
        self.assertEqual(store.list_daily_files('agents'), [])
        self.assertEqual(len(store.list_daily_files('repos')), 1)


if __name__ == '__main__':
    unittest.main()
