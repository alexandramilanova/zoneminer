"""Persistent zone-independent replay tables, serialized across concurrent jobs."""
import fcntl
import hashlib
import json
import os

from backend import store

REPLAY_CACHE_VERSION = 'canonical-alignment-replay-v4'
TABLES = ('token_place', 'conformance', 'alignment_moves')


def get_replay_tables(dataset_id, backend, compute, progress=None):
    key = 'replay-' + hashlib.sha256(json.dumps([REPLAY_CACHE_VERSION, dataset_id, backend]).encode()).hexdigest()[:20]
    directory = store.analysis_dir(key)
    os.makedirs(directory, exist_ok=True)
    marker = os.path.join(directory, 'complete.json')
    with open(os.path.join(directory, 'cache.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(marker):
            frames = [store.load_frame(key, name) for name in TABLES]
            if all(frame is not None for frame in frames):
                tokens, conformance, moves = frames
                tokens['time_spent'] = tokens['consumed_ts'] - tokens['produced_ts']
                if progress:
                    for stage in ('align', 'replay', 'conformance'):
                        progress(stage, 'done', 'Reused validated replay tables; independent of zones and timeframe')
                return tokens, conformance, moves
        frames = compute()
        for name, frame in zip(TABLES, frames):
            store.save_frame(key, name, frame.drop(columns=['time_spent'], errors='ignore'))
        with open(marker + '.tmp', 'w') as stream:
            json.dump(dict(version=REPLAY_CACHE_VERSION, dataset=dataset_id, backend=backend), stream)
        os.replace(marker + '.tmp', marker)
        return frames
