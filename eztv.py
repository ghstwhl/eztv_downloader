#!/usr/bin/env python3
"""EZTV Downloader - Fetches TV show torrents from EZTV and queues them in Transmission."""

import json
import logging
import os
import argparse
from operator import itemgetter
from collections import defaultdict
import re
from bs4 import BeautifulSoup
import transmissionrpc
import requests
import sys
import time

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


API_URLS = [
    "https://eztvx.to/api/get-torrents",
    "https://eztv.tf/api/get-torrents"
]

# Retry/backoff configuration for HTTP requests
REQUEST_MAX_RETRIES = 3
REQUEST_BACKOFF_FACTOR = 0.5

# Home directory of the user running the script
HOMEDIR = os.path.expanduser("~")


HTTP_HEADERS = {
    "Accept-Encoding":"gzip, deflate", 
    "Accept": "application/json",
    "Connection": "close",
    "Content-Type":"application/json",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0",
    }

def cli():
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description='Fetch TV show torrents from EZTV and queue them in Transmission.')
    parser.add_argument('--add', action='append', help="Add a show to track, using the IMDB id.")
    parser.add_argument('--list', action='store_true', help="List all shows being tracked.")
    parser.add_argument('--list-downloaded', action='store_true', help="List downloaded episodes.")
    parser.add_argument('--deactivate', action='append', help="Deactivate shows in the cache, but retain the data.")
    parser.add_argument('--purge', action='append', help="Purge shows from the cache")
    parser.add_argument('--only', action='append', help="For this run, only download these shows.")
    parser.add_argument('--transmission-host', default='localhost', help="Transmission RPC host. Default: localhost")
    parser.add_argument('--transmission-port', type=int, default=9091, help="Transmission RPC port. Default: 9091")
    parser.add_argument('--page-count', type=int, default=20, help="Number of pages to fetch from EZTV. Default: 20")
    return parser.parse_args()

def read_cache():
    """Read or initialize the cache"""
    eztv_cache = os.path.join(HOMEDIR, '.eztv', 'downloader.json')
    if os.path.isfile(eztv_cache):
        logger.info("Reading cache...")
        with open(eztv_cache, 'r') as f:
            cache_dict = json.load(f)
    else:
        logger.info("Initializing cache...")
        cache_dict = {}
    return cache_dict

def write_cache(data):
    """Write the cache"""
    # Ensure the ~/.eztv directory exists
    eztv_dir = os.path.join(HOMEDIR, '.eztv')
    if not os.path.isdir(eztv_dir):
        os.makedirs(eztv_dir, exist_ok=True)

    try:
        with open(os.path.join(eztv_dir, 'downloader.json'), 'w') as outfile:
            json.dump(data, outfile, indent=4)
        return True
    except Exception as e:
        logger.error(f"Failed to write cache: {e}")
        return False


def get_imdb_meta(imdb_id, headers=HTTP_HEADERS):
    """Get IMDB meta data"""
    imdb_url = f"https://www.imdb.com/title/tt{imdb_id}/"
    try:
        resp = requests.get(imdb_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch IMDB data for {imdb_id}: {e}")
        return False
    
    if resp.status_code == 404:
        logger.warning(f"IMDB ID {imdb_id} not found")
        return False
    
    try:
        content = BeautifulSoup(resp.content, 'lxml')
        title = content.find("meta", property="og:title")
        url = content.find("meta", property="og:url")
        return {
            'title': title["content"] if title else "No meta title given",
            'url': url["content"] if url else "No meta url given"
        }
    except Exception as e:
        logger.error(f"Error parsing IMDB page for {imdb_id}: {e}")
        return False

def convert_cache(cache_dict):
    """Update cache format, if necessary"""
    if 'version' not in cache_dict or cache_dict['version'] < 2:
        logger.info("Converting cache to v2 format...")
        new_cache = {
            'version': 2,
            'shows': {}
        }
        for show in cache_dict:
            new_cache['shows'][show] = {}
            show_meta_data = get_imdb_meta(show)
            if show_meta_data:
                new_cache['shows'][show]['url'] = show_meta_data['url']
                new_cache['shows'][show]['title'] = show_meta_data['title']
            new_cache['shows'][show]['status'] = 'active'
            new_cache['shows'][show]['seasons'] = cache_dict[show]
        return new_cache
    else:
        logger.info("Data format already current")
        return None

def purge_shows(cache_dict, shows):
    """Purge shows"""
    purged_something = False
    for imdb_id in shows:
        if imdb_id in cache_dict['shows']:
            logger.info(f"Purging {cache_dict['shows'][imdb_id]['title']}")
            del cache_dict['shows'][imdb_id]
            purged_something = True
    if purged_something:
        write_cache(cache_dict)
        logger.info("Cache updated")
    return purged_something

def remove_shows(cache_dict, shows):
    """Mark show inactive"""
    for imdb_id in shows:
        if imdb_id in cache_dict['shows']:
            logger.info(f"Deactivating {cache_dict['shows'][imdb_id]['title']}")
            cache_dict['shows'][imdb_id]['status'] = 'inactive'
    return cache_dict

def list_shows(cache_dict):
    """List shows in cache"""
    logger.info("Shows in cache:")
    if 'shows' in cache_dict:
        for show in cache_dict['shows']:
            logger.info(f"{show:<9} - {cache_dict['shows'][show]['status']:<8} - {cache_dict['shows'][show]['url']:<39} - {cache_dict['shows'][show]['title']}")
    else:
        logger.info("No show data in cache.")

def add_shows(cache_dict, shows):
    """Add show to cache"""
    for imdb_id in shows:
        imdb_id = re.sub(r'^(vv|)(\d+)$', r'\2', imdb_id, flags=re.IGNORECASE)
        if imdb_id in cache_dict['shows']:
            logger.info(f"Skipping {imdb_id:<9} - already in cache:  {cache_dict['shows'][imdb_id]['title']}")
        else:
            show_meta_data = get_imdb_meta(imdb_id)
            if not show_meta_data:
                logger.warning(f"Skipping {imdb_id:<9} - not found in IMDB")
            else:
                logger.info(f"Adding {imdb_id:<9} - {show_meta_data['title']}")
                cache_dict['shows'][imdb_id] = {
                    'url': show_meta_data['url'],
                    'title': show_meta_data['title'],
                    'seasons': {},
                    'status': 'active'
                }
    return cache_dict

def fetch_eztv_data(page_count):
    """Retrieve torrent data from eztv API with retry/backoff on transient errors.
    
    Tries each URL in API_URLS in sequence, retrying with backoff for transient errors.
    """
    logger.info("Fetching EZTV data...")
    torrents = []
    for page in range(0, page_count):
        logger.info(f"  Fetching page {page}...")

        resp = None
        for url_index, current_url in enumerate(API_URLS):
            for attempt in range(1, REQUEST_MAX_RETRIES + 1):
                try:
                    params = {'limit': 100, 'page': page}
                    resp = requests.get(current_url, params=params, headers=HTTP_HEADERS, timeout=10)
                    resp.raise_for_status()
                    break
                except requests.exceptions.RequestException as err:
                    if attempt == REQUEST_MAX_RETRIES:
                        logger.error(f"Error fetching page {page} from {current_url}: {err} (failed after {REQUEST_MAX_RETRIES} attempts)")
                    else:
                        sleep_time = REQUEST_BACKOFF_FACTOR * (2 ** (attempt - 1))
                        logger.warning(f"Transient error fetching page {page}: {err}. Retrying in {sleep_time:.1f}s... (attempt {attempt}/{REQUEST_MAX_RETRIES})")
                        time.sleep(sleep_time)
                    resp = None
            
            if resp is not None:
                break
            elif url_index < len(API_URLS) - 1:
                logger.info("Trying next API URL...")

        if resp is None:
            logger.warning(f"Failed to fetch page {page} from all API URLs")
            continue

        if resp.status_code == 404:
            logger.error(f"Page not found: {resp.url}")
            return torrents
        if resp.status_code != 200:
            logger.error(f"HTTP {resp.status_code}: {resp.reason} - {resp.url}")
            continue

        try:
            parsed_data = resp.json()
        except ValueError as err:
            logger.error(f"Failed to parse JSON for page {page}: {err}")
            continue

        if 'torrents' in parsed_data:
            torrents += parsed_data['torrents']

    return torrents

def best_torrent_match(torrent_list):
    """Apply some logic to find the best torrent from those available."""
    if not torrent_list:
        logger.error("No torrents available to match")
        return None
    
    for codec in ['HEVC', 'H265', 'X265', 'H264', 'X264']:
        for size in ['1080P', '720P', 'HDTV', '480P']:
            for x in torrent_list:
                file_name = x['filename'].upper()
                if codec in file_name and size in file_name:
                    return {
                        'filename': x['filename'],
                        'magnet_link': x['magnet_url']
                    }
    # Fallback to most seeded torrent
    losers_choice = sorted(torrent_list, key=itemgetter('seeds'), reverse=True)[0]
    return {
        'filename': losers_choice['filename'],
        'magnet_link': losers_choice['magnet_url']
    }


def main():
    """Main entrypoint.

    Parses CLI arguments, connects to Transmission RPC, fetches EZTV data,
    queues torrents, and updates the local cache as needed.
    """
    logger.info("EZTV Downloader starting...")
    args = cli()

    try:
        tc = transmissionrpc.Client(args.transmission_host, port=args.transmission_port)
    except Exception as e:
        logger.error(f"Error: could not connect to Transmission RPC ({args.transmission_host}:{args.transmission_port}): {e}")
        logger.error("Please ensure the Transmission daemon (transmission-daemon) is running and accessible.")
        logger.error("If Transmission is running on a different host or port, re-run with --transmission-host and --transmission-port to point to the correct RPC endpoint.")
        logger.error("Example: eztv --transmission-host 192.168.1.100 --transmission-port 9091")
        sys.exit(1)

    cache_dict = read_cache()
    cache_update = False

    if args.purge:
        logger.info("--purge handling...")
        if purge_shows(cache_dict, args.purge):
            return

    if args.deactivate:
        logger.info("--deactivate handling...")
        cache_dict = remove_shows(cache_dict, args.deactivate)
        write_cache(cache_dict)
        return

    if args.add:
        cache_dict = add_shows(cache_dict, args.add)
        cache_update = True
        
    if args.list_downloaded:
        import json
        logger.info(json.dumps(cache_dict, indent=2))
        return

    if args.list:
        list_shows(cache_dict)
        return

    messages = []
    eztv_data = fetch_eztv_data(args.page_count)
    
    # Build a lookup for torrents by show/season/episode for efficiency
    torrents_by_key = defaultdict(list)
    for torrent in eztv_data:
        key = (torrent['imdb_id'], torrent['season'], torrent['episode'])
        torrents_by_key[key].append(torrent)
    
    for imdb_id in cache_dict['shows']:
        if cache_dict['shows'][imdb_id]['status'] != 'active':
            continue
        if args.only is not None and imdb_id not in args.only:
            continue
        logger.info(f"Checking: {imdb_id} - {cache_dict['shows'][imdb_id]['title']}")
        
        for season in set([x['season'] for x in eztv_data if x['imdb_id'] == imdb_id]):
            if season not in cache_dict['shows'][imdb_id]['seasons']:
                cache_dict['shows'][imdb_id]['seasons'][season] = {}
            
            for episode in set([x['episode'] for x in eztv_data if x['imdb_id'] == imdb_id and x['season'] == season]):
                if episode not in cache_dict['shows'][imdb_id]['seasons'][season]:
                    key = (imdb_id, season, episode)
                    best_link = best_torrent_match(torrents_by_key[key])
                    if best_link:
                        tc.add_torrent(best_link['magnet_link'])
                        cache_dict['shows'][imdb_id]['seasons'][season][episode] = best_link['magnet_link']
                        cache_update = True
                        messages.append(f"ADDED {cache_dict['shows'][imdb_id]['title']} - Season {season} - {episode} - {best_link['filename']}")

    for msg in messages:
        logger.info(msg)
        
    if cache_update:
        write_cache(cache_dict)

if __name__ == '__main__':
    main()

