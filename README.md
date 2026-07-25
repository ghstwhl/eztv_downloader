# EZTV Downloader

Fetches TV show torrents from the EZTV API and queues them in Transmission.

**Disclaimer:** This code was developed and tested with the aid of AI tooling.

## Features

- Fetches torrent metadata from the EZTV API with concurrent page requests
- Picks the best torrent per episode (HEVC > H265 > X265 > H264 > X264; 1080p > 720p > HDTV > 480p)
- Falls back to the most-seeded torrent when codec and resolution preferences don't match
- Adds torrents to Transmission via RPC
- Tracks downloaded episodes in a JSON cache (`~/.eztv/downloader.json`)
- Retries transient API errors with exponential backoff
- Auto-converts legacy v1 cache format to v2

## Requirements

- **Python** ≥ 3.13
- **Transmission** daemon with RPC enabled
- **pipenv** (recommended) or plain `pip` + venv

## Installation

### Using pipenv (recommended)

```bash
cd eztv_downloader
pipenv install
```

### Using plain pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install transmission-rpc requests
```

## Usage

### Quick start

```bash
# Show all options
python eztv.py --help

# Add shows to track (use the numeric IMDB id — the 'tt' prefix is optional)
python eztv.py --add 12327578

# Add multiple at once
python eztv.py --add 12327578 --add 0452046 --add 14688458

# List all tracked shows and their status
python eztv.py --list

# Run the downloader (defaults to Transmission at localhost:9091)
python eztv.py
```

### Full option reference

| Flag | Description |
|---|---|
| `--add IMDB_ID` | Add a show to track. Repeatable. Accepts plain numeric ID or `tt`/`vv`-prefixed. |
| `--list` | List all tracked shows with status, URL, and title. |
| `--list-downloaded` | Dump the full cache as JSON. |
| `--deactivate IMDB_ID` | Mark a show inactive (keep its download history). Repeatable. |
| `--purge IMDB_ID` | Remove a show and its download history entirely. Repeatable. |
| `--only IMDB_ID` | For this run, only process the given shows. Repeatable. |
| `--transmission-host HOST` | Transmission RPC host. Default: `localhost`. |
| `--transmission-port PORT` | Transmission RPC port. Default: `9091`. |
| `--page-count N` | Number of EZTV API pages to fetch (100 torrents per page). Default: `20`. |

### Setting up a shortcut

Add this alias to your `~/.zshrc` or `~/.bashrc`:

```bash
alias eztv='source /path/to/venv/bin/activate; /path/to/eztv_downloader/eztv.py'
```

Then just run `eztv` from anywhere.

## How it works

1. **Parse CLI args** — determines which action to take (add shows, list, download, etc).
2. **Connect to Transmission** — establishes an RPC connection with the configured host and port.
3. **Read cache** — loads `~/.eztv/downloader.json`, auto-converting v1 caches to v2 format if needed.
4. **Perform early-exit actions** — `--purge`, `--deactivate`, `--add`, `--list`, and `--list-downloaded` return immediately after their work is done.
5. **Fetch EZTV data** — fetches torrent metadata across multiple API pages concurrently (5 workers), with URL fallback and retry/backoff on transient errors.
6. **Match torrents** — for each active show, finds available seasons and episodes in the EZTV data. Picks the best torrent by codec and resolution preference, falling back to the most-seeded option.
7. **Queue in Transmission** — adds the chosen magnet link to Transmission via RPC.
8. **Update cache** — records newly downloaded episodes and writes the cache back to disk.

## Cache format

The cache lives at `~/.eztv/downloader.json`. The v2 format:

```json
{
  "version": 2,
  "shows": {
    "12327578": {
      "title": "Star Trek: Strange New Worlds",
      "url": "https://www.imdb.com/title/tt12327578/",
      "status": "active",
      "seasons": {
        "1": {"1": "magnet:?...", "2": "magnet:?..."},
        "2": {"1": "magnet:?..."}
      }
    }
  }
}
```

- `status`: `active` shows are processed during download runs; `inactive` shows are skipped but retain their download history.
- `seasons`: tracks which episodes have been downloaded so future runs skip them.

## Notes

- **Transmission must be running** with RPC enabled. If the script can't connect, it exits with a clear error message including the host and port it tried.
- The EZTV API is accessed at `eztvx.to` and `eztv.tf` as fallback. No API key is required.
- IMDB metadata (show titles and URLs) is fetched from the IMDB suggestion API when adding new shows.
- Page fetching is concurrent (5 threads) to minimize total wait time. Each individual page still benefits from URL fallback and retry/backoff.

## Running tests

```bash
pipenv install --dev    # or: pip install pytest transmission-rpc requests
python -m pytest -v
```

## Contributing

Feel free to open issues or PRs. Keep changes focused and add tests if appropriate.

## Copyright

Copyright © Chris Knight — https://github.com/ghstwhl

## License

See the `LICENSE` file in the repository.
