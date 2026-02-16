#!/usr/bin/env python3

import json
import pprint
import os
import argparse
from operator import itemgetter
import re
from bs4 import BeautifulSoup
import transmissionrpc
import requests
import sys
import time


API_URLS = [
    "https://eztvx.to/api/get-torrents",
    "https://eztv.tf/api/get-torrents"
]

# Retry/backoff configuration for HTTP requests
REQUEST_MAX_RETRIES = 3
REQUEST_BACKOFF_FACTOR = 0.5

pp = pprint.PrettyPrinter(indent=2)

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
    parser = argparse.ArgumentParser(description='Feed me nagios variables and I shit emails!')
    parser.add_argument('--add', action='append', help="Add a show to track, usign the IMDB id.")
    parser.add_argument('--list', action='store_true', help="List all shows being tracked.")
    parser.add_argument('--list-downloaded', action='store_true', help="List downloaded episodes.")
    parser.add_argument('--deactivate', action='append', help="Deactivate shows in the cache, but retain the data.")
    parser.add_argument('--purge', action='append', help="Purge shows from the cache")
    parser.add_argument('--only', action='append', help="For this run, only download these shows.")
    parser.add_argument('--nosave', action='store_true', help="Perform downloads without saving episodes to the cache. Useful when you intend to re-download later.")
    parser.add_argument('--transmission-host', default='localhost', help="Transmission RPC host. Default: localhost")
    parser.add_argument('--transmission-port', type=int, default=9091, help="Transmission RPC port. Default: 9091")
    parser.add_argument('--page-count', type=int, default=20, help="Number of pages to fetch from EZTV. Default: 20")
    return parser.parse_args()

def read_cache():
    """Read or initialize the cache"""
    eztv_cache = os.path.join(HOMEDIR, '.eztv', 'downloader.json')
    if os.path.isfile(eztv_cache):
        print("Reading cache...")
        with open(eztv_cache, 'r') as f:
            cache_dict = json.load(f)
    else:
        print("Initializing cache...")
        cache_dict = {}
    return cache_dict

def write_cache(data):
    """Write the cache"""
    # Ensure the ~/.eztv directory exists
    eztv_dir = os.path.join(HOMEDIR, '.eztv')
    if not os.path.isdir(eztv_dir):
        os.makedirs(eztv_dir, exist_ok=True)

    with open(os.path.join(eztv_dir, 'downloader.json'), 'w') as outfile:
        json.dump(data, outfile, indent=4)
        outfile.close()
        return True

    return False


def get_imdb_meta(imdb_id, headers=HTTP_HEADERS):
    """Get IMDB meta data"""
    imdb_url=f"https://www.imdb.com/title/tt{imdb_id}/"
    try:
        resp = requests.get(imdb_url, headers=headers, timeout=10)
    except Exception:
        print("something something...")
    else:
        if 404 == resp.status_code:
            return False
        else:
            content = BeautifulSoup(resp.content, 'lxml')
            title = content.find("meta", property="og:title")
            url = content.find("meta", property="og:url")
            return {
                'title': title["content"] if title else "No meta title given",
                'url': url["content"] if url else "No meta url given"
            }

    return False

def convert_cache(cache_dict):
    """Update cache format, if necessary"""
    if 'version' not in cache_dict or 2 < cache_dict['version']:
        new_cache = {
            'version': 2,
            'shows': {}
        }
        for show in cache_dict:
            new_cache['shows'][show] = {}
            show_meta_data = get_imdb_meta(show)
            if show_meta_data is not False:
                new_cache['shows'][show]['url'] = show_meta_data['url']
                new_cache['shows'][show]['title'] = show_meta_data['title']
            new_cache['shows'][show]['status'] = 'active'
            new_cache['shows'][show]['seasons'] = cache_dict[show]
        return new_cache
    else:
        print("Data format already current")
        return False

def purge_shows(cache_dict, shows):
    """Purge shows"""
    purged_something = False
    for imdb_id in shows:
        if imdb_id in cache_dict['shows']:
            print(f"Purging {cache_dict['shows'][imdb_id]['title']}")
            del cache_dict['shows'][imdb_id]
            purged_something = True
    if purged_something:
        write_cache(cache_dict)
    exit()

def remove_shows(cache_dict, shows):
    """Mark show inactive"""
    for imdb_id in shows:
        if imdb_id in cache_dict['shows']:
            print(f"Deactivating {cache_dict['shows'][imdb_id]['title']}")
            cache_dict['shows'][imdb_id]['status'] = 'inactive'
    return cache_dict

def list_shows(cache_dict):
    """list shows in cache"""
    print("Shows in cache:")
    if 'shows' in cache_dict:
        for show in cache_dict['shows']:
            print(f"{show:<9} - {cache_dict['shows'][show]['status']:<8} - {cache_dict['shows'][show]['url']:<39} - {cache_dict['shows'][show]['title']}")
    else:
        print("No show data in cache.")

def add_shows(cache_dict, shows):
    """add show to cache"""
    for imdb_id in shows:
        imdb_id = re.sub(r'^(vv|)(\d+)$', r'\2', imdb_id, flags=re.IGNORECASE)
        if imdb_id in cache_dict['shows']:
            print(f"Skipping {imdb_id:<9} - already in cache:  {cache_dict['shows'][imdb_id]['title']}")
        else:
            show_meta_data = get_imdb_meta(imdb_id)
            if not show_meta_data:
                print(f"Skipping {imdb_id:<9} - not found in IMDB")
            else:
                print(f"Adding {imdb_id:<9} - {show_meta_data['title']}")
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

    print("Fetching EZTV data...")
    torrents = []
    for page in range(0, page_count):  # EZTV has a lot of pages; adjust as needed
        print(f"  Fetching page {page}...")

        # Try with retries/backoff for transient errors
        resp = None
        for url_index, current_url in enumerate(API_URLS):
            for attempt in range(1, REQUEST_MAX_RETRIES + 1):
                try:
                    params = {'limit': 100, 'page': page}
                    resp = requests.get(current_url, params=params, headers=HTTP_HEADERS, timeout=10)
                    resp.raise_for_status()
                    break  # Success, exit attempt loop
                except requests.exceptions.RequestException as err:
                    if attempt == REQUEST_MAX_RETRIES:
                        print(f"Error fetching page {page} from {current_url}: {err} (failed after {REQUEST_MAX_RETRIES} attempts)")
                    else:
                        sleep_time = REQUEST_BACKOFF_FACTOR * (2 ** (attempt - 1))
                        print(f"Transient error fetching page {page}: {err}. Retrying in {sleep_time:.1f}s... (attempt {attempt}/{REQUEST_MAX_RETRIES})")
                        time.sleep(sleep_time)
                    resp = None
            
            if resp is not None:
                break  # Success with this URL, exit URL loop
            elif url_index < len(API_URLS) - 1:
                print(f"Trying next API URL...")

        # If we didn't get a successful response, skip this page
        if resp is None:
            print(f"Failed to fetch page {page} from all API URLs")
            continue

        if resp.status_code == 404:
            print("Page not found?")
            print(resp.url)
            print(resp.request)
            return torrents
        if resp.status_code != 200:
            print(resp.status_code)
            print(resp.reason)
            print(resp.request)
            print(resp.text)
            print(resp.url)
            continue

        try:
            parsed_data = resp.json()
        except ValueError as err:
            print(f"Failed to parse JSON for page {page}: {err}")
            continue

        if 'torrents' in parsed_data:
            torrents += parsed_data['torrents']

    return torrents

def best_torrent_match(torrent_list):
    """Apply some logic to find the best torrent from those available."""
    for codec in ['HEVC', 'H265', 'X265', 'H264', 'X264']:
        for size in ['1080P', '720P', 'HDTV', '480P']:
            for x in torrent_list:
                file_name = x['filename'].upper()
                if codec in file_name and size in file_name:
                    return {
                        'filename': x['filename'],
                        'magnet_link': x['magnet_url']
                    }
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
    print("EZTV Downloader starting...")
    args = cli()

    try:
        tc = transmissionrpc.Client(args.transmission_host, port=args.transmission_port)
    except Exception as e:
        print(f"Error: could not connect to Transmission RPC ({args.transmission_host}:{args.transmission_port}): {e}")
        # Provide actionable guidance to the user so they can resolve connection issues
        print("Please ensure the Transmission daemon (transmission-daemon) is running and accessible.")
        print("If Transmission is running on a different host or port, re-run with --transmission-host and --transmission-port to point to the correct RPC endpoint.")
        print("Example: eztv --transmission-host 192.168.1.100 --transmission-port 9091")
        sys.exit(1)

    cache_dict = read_cache()
    cache_update = False

    if args.purge is not None and 0 < len(args.purge):
        print("--purge handling...")
        purge_shows(cache_dict, args.purge)


    if args.deactivate is not None and 0 < len(args.deactivate):
        print("--deactivate handling...")
        cache_dict = remove_shows(cache_dict, args.deactivate)
        write_cache(cache_dict)
        exit()

    if args.add is not None and 0 < len(args.add):
        cache_dict = add_shows(cache_dict, args.add)
        cache_update = True
        
    if args.list_downloaded:
        pp.pprint(cache_dict)
        exit()

    if args.list:
        list_shows(cache_dict)
        exit()

    messages = []
    eztv_data=fetch_eztv_data(args.page_count)
    for imdb_id in cache_dict['shows']:
        if 'active' != cache_dict['shows'][imdb_id]['status']:
            continue
        if args.only is not None and imdb_id not in args.only:
            continue
        print(f"Checking: {imdb_id} - {cache_dict['shows'][imdb_id]['title']}")
        for season in set([x['season'] for x in eztv_data if x['imdb_id'] == imdb_id]):
            if season not in cache_dict['shows'][imdb_id]['seasons']:
                    cache_dict['shows'][imdb_id]['seasons'][season] = {}
            for episode in set([x['episode'] for x in eztv_data if x['imdb_id'] == imdb_id and x['season'] == season]):
                if episode not in cache_dict['shows'][imdb_id]['seasons'][season]:
                    episode_list = [x for x in eztv_data if x['imdb_id'] == imdb_id and x['season'] == season and x['episode'] == episode]
                    best_link = best_torrent_match(episode_list)
                    if best_link is not False:
                        tc.add_torrent(best_link['magnet_link'])
                        cache_dict['shows'][imdb_id]['seasons'][season][episode]=best_link['magnet_link']
                        cache_update = True
                        messages.append(f"ADDED {cache_dict['shows'][imdb_id]['title']} - Season {season} - {episode} - {best_link['filename']}")

    for msg in messages:
        print(msg)
        
    if cache_update:
        write_cache(cache_dict)

if __name__ == '__main__':
    main()

