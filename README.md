# EZTV Downloader

Small utility that fetches TV show torrents from EZTV and queues them in Transmission.

**Disclaimer:** This code has been developed and tested with the aid of AI tooling (GitHub Copilot).

Features
- Fetches torrent metadata from the EZTV API
- Picks a preferred torrent (HEVC/H264, 1080p/720p, seeded)
- Adds torrents to Transmission via RPC
- Tracks downloads in a simple JSON cache (~/.eztv/downloader.json)

Requirements
- Python 3.13
- Transmission (with RPC enabled)
- pipenv (recommended for development)

Installation (local development)

1. Install pipenv (if not already):

```bash
pip3 install --user pipenv
export PATH="$HOME/.local/bin:$PATH"
```

2. Install dependencies and create a virtualenv:

```bash
cd eztv_downloader
pipenv install
pipenv shell      # optional: spawn a shell inside the environment
```

Running without a virtualenv (e.g. in a container / devcontainer)

```bash
cd eztv_downloader
pipenv lock
PIPENV_PIPFILE=./Pipfile pipenv install --deploy --system
```

Usage

```bash
# Show help
python eztv.py --help

# Add a show to track (IMDB id)
python eztv.py --add 1234567

# List tracked shows
python eztv.py --list

# Run downloader (default connects to localhost:9091)
python eztv.py
```

Options of interest
- `--transmission-host` and `--transmission-port`: Transmission RPC connection
- `--page-count`: number of EZTV API pages to fetch (default 20)
- `--nosave`: perform downloads without saving to cache

Cache and data
- Cache file: `~/.eztv/downloader.json` (auto-created)

Notes
- Transmission must be running and have RPC enabled for the script to add torrents. The script will exit with a clear message if it cannot connect to Transmission.
- The `Pipfile` lists the runtime dependencies (`transmissionrpc`, `beautifulsoup4`). Use `pipenv` to manage them.

Contributing
- Feel free to open issues or PRs. Keep changes focused and add tests if appropriate.

Copyright
- Copyright © Chris Knight - https://github.com/ghstwhl

License
- See the `LICENSE` file in the repository.
