import os
import json
import types
import sys
import pytest

import sys
import pathlib

# Ensure the repository root is on sys.path so tests can import the script as a module
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import eztv


def test_read_and_write_cache(tmp_path, monkeypatch):
    # Point HOMEDIR to a temp dir
    monkeypatch.setattr(eztv, 'HOMEDIR', str(tmp_path))
    # Ensure no cache exists
    cache = eztv.read_cache()
    assert cache == {}

    data = {"shows": {"123": {"title": "Test Show"}}}
    assert eztv.write_cache(data) is True

    # Read back and compare
    new_cache = eztv.read_cache()
    assert new_cache == data


def test_best_torrent_match_prefers_codec_and_size():
    torrents = [
        {"filename": "show.s01e01.720p.H264.mkv", "magnet_url": "m1", "seeds": 5},
        {"filename": "show.s01e01.1080p.H265.mkv", "magnet_url": "m2", "seeds": 3},
        {"filename": "show.s01e01.480p.X264.mkv", "magnet_url": "m3", "seeds": 10},
    ]
    pick = eztv.best_torrent_match(torrents)
    assert pick["magnet_link"] == "m2"
    assert "1080" in pick["filename"].upper()


def test_best_torrent_match_falls_back_to_most_seeded():
    torrents = [
        {"filename": "a.mkv", "magnet_url": "m1", "seeds": 2},
        {"filename": "b.mkv", "magnet_url": "m2", "seeds": 9},
        {"filename": "c.mkv", "magnet_url": "m3", "seeds": 5},
    ]
    pick = eztv.best_torrent_match(torrents)
    assert pick["magnet_link"] == "m2"


def test_cli_defaults(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['eztv.py'])
    args = eztv.cli()
    assert args.page_count == 20
    assert args.transmission_host == 'localhost'
    assert args.transmission_port == 9091


def test_get_imdb_meta_handles_errors(monkeypatch):
    class DummyResp:
        def __init__(self, status_code=404, content=b""):
            self.status_code = status_code
            self.content = content
        
        def raise_for_status(self):
            if self.status_code >= 400:
                raise eztv.requests.exceptions.HTTPError()

    def raise_exc(*a, **kw):
        # raise the same exception type that `eztv.requests` would raise
        raise eztv.requests.exceptions.RequestException()

    # Patch requests.get to raise an exception
    monkeypatch.setattr(eztv.requests, 'get', raise_exc)
    assert eztv.get_imdb_meta('0000000') is False

    # Patch requests.get to return 404
    monkeypatch.setattr(eztv.requests, 'get', lambda *a, **kw: DummyResp(404))
    assert eztv.get_imdb_meta('0000000') is False


def test_fetch_eztv_data_handles_timeout(monkeypatch):
    class DummyResp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data or {}
            self.url = "https://eztvx.to/api/get-torrents"
            self.request = None
            self.reason = "OK"
            self.text = json.dumps(self._data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise eztv.requests.exceptions.HTTPError()

        def json(self):
            return self._data

    # Simulate a successful first page and then a timeout on later pages
    def side_effect(url, params=None, headers=None, timeout=None):
        page = (params or {}).get('page')
        if page == 0:
            return DummyResp(200, {'torrents': [{'imdb_id': '1', 'season': 1, 'episode': 1, 'filename': 'a.mkv', 'magnet_url': 'm1', 'seeds': 1}]})
        else:
            raise eztv.requests.exceptions.ReadTimeout()

    monkeypatch.setattr(eztv.requests, 'get', side_effect)

    # Should not raise and should return the torrents collected from successful pages
    torrents = eztv.fetch_eztv_data(3)
    assert any(t.get('magnet_url') == 'm1' for t in torrents)


def test_fetch_eztv_data_retries_and_succeeds(monkeypatch):
    class DummyResp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data or {}
            self.url = "https://eztvx.to/api/get-torrents"
            self.request = None
            self.reason = "OK"
            self.text = json.dumps(self._data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise eztv.requests.exceptions.HTTPError()

        def json(self):
            return self._data

    counters = {'page1': 0}

    def side_effect(url, params=None, headers=None, timeout=None):
        page = (params or {}).get('page')
        if page == 0:
            return DummyResp(200, {'torrents': [{'imdb_id': '1', 'season': 1, 'episode': 1, 'filename': 'a.mkv', 'magnet_url': 'm1', 'seeds': 1}]})
        elif page == 1:
            counters['page1'] += 1
            # Fail the first two attempts, succeed on the 3rd
            if counters['page1'] < 3:
                raise eztv.requests.exceptions.ReadTimeout()
            return DummyResp(200, {'torrents': [{'imdb_id': '2', 'season': 1, 'episode': 2, 'filename': 'b.mkv', 'magnet_url': 'm2', 'seeds': 1}]})
        else:
            return DummyResp(200, {})

    monkeypatch.setattr(eztv.requests, 'get', side_effect)

    torrents = eztv.fetch_eztv_data(2)
    assert any(t.get('magnet_url') == 'm1' for t in torrents)
    assert any(t.get('magnet_url') == 'm2' for t in torrents)


def test_main_skips_inactive_shows(monkeypatch, tmp_path):
    """Test that shows with 'inactive' status are skipped during download processing."""
    import unittest.mock as mock

    # Set up test cache with one active and one inactive show
    cache_dict = {
        'version': 2,
        'shows': {
            '111': {
                'title': 'Active Show',
                'url': 'http://imdb.com/title/tt111',
                'status': 'active',
                'seasons': {}
            },
            '222': {
                'title': 'Inactive Show',
                'url': 'http://imdb.com/title/tt222',
                'status': 'inactive',
                'seasons': {}
            }
        }
    }

    # Mock Transmission client
    mock_tc = mock.MagicMock()

    # Mock fetch_eztv_data to return torrents for both shows
    eztv_data = [
        {'imdb_id': '111', 'season': 1, 'episode': 1, 'filename': 'active.s01e01.mkv', 'magnet_url': 'm_active', 'seeds': 5},
        {'imdb_id': '222', 'season': 1, 'episode': 1, 'filename': 'inactive.s01e01.mkv', 'magnet_url': 'm_inactive', 'seeds': 5},
    ]

    # Mock functions
    monkeypatch.setattr(eztv, 'read_cache', lambda: cache_dict)
    monkeypatch.setattr(eztv, 'write_cache', lambda x: True)
    monkeypatch.setattr(eztv, 'fetch_eztv_data', lambda x: eztv_data)
    monkeypatch.setattr(eztv.transmissionrpc, 'Client', lambda *args, **kwargs: mock_tc)

    # Mock sys.argv to simulate no arguments
    monkeypatch.setattr(sys, 'argv', ['eztv.py'])

    # Call main
    eztv.main()

    # Verify that only the active show's torrent was added
    assert mock_tc.add_torrent.call_count == 1
    call_args = mock_tc.add_torrent.call_args
    assert call_args[0][0] == 'm_active'
