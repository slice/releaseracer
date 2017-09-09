import json
import logging
import sys


from releaseracer.bot import ReleaseRacer

log = logging.getLogger('releaseracer.launcher')

# configure logging
logging.basicConfig(level=logging.INFO)


def read_configuration(file_name: str) -> dict:
    try:
        with open(file_name, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        log.fatal('configuration file (config.json) not found')
        sys.exit(1)


cfg = read_configuration('config.json')
rr = ReleaseRacer(cfg)
rr.run(cfg['token'])
