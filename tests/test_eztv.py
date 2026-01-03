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

    def raise_exc(*a, **kw):
        # raise the same exception type that `eztv.requests` would raise
        raise eztv.requests.exceptions.RequestException()

    # Patch requests.get to raise an exception
    monkeypatch.setattr(eztv.requests, 'get', raise_exc)
    assert eztv.get_imdb_meta('0000000') is False

    # Patch requests.get to return 404
    monkeypatch.setattr(eztv.requests, 'get', lambda *a, **kw: DummyResp(404))
    assert eztv.get_imdb_meta('0000000') is False
