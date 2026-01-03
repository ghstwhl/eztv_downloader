#!/usr/bin/env python3

import json
import os
import pickle

CACHE='/Users/merlin/Repos/Scripts/eztv.cache'

# Home directory of the user running the script
HOMEDIR = os.path.expanduser("~")

def get_cache():
    """Read the cache"""
    print("Reading cache...")
    if os.path.isfile(CACHE):
        with open(CACHE, 'rb') as f:
            cache_dict = pickle.load(f)
    else:
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


if __name__ == '__main__':
    cache_date = get_cache()
    write_cache(cache_date)
    print("Conversion complete.")

