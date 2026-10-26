#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    heating_history.py
# Description: Bounded, sparse heating history and recorded controller decisions.
# Author:      CliveS & Codex GPT-6
# Date:        26-10-2026
# Version:     1.0

import math
import os
import re
from datetime import datetime, timedelta, timezone

FIELDS = ('temperatureinput1', 'temperature', 'setpointheat', 'hvacheaterison',
          'temperatureseenepoch', 'gatewaystatus', 'setpointsource')
ROW_LIMIT = 30000
GAP_SECONDS = 10800


def read_history(owner, hist, conn, device_id, columns, hours, now=None):
    """No averaging of targets or booleans. Read only a bounded PK interval.

    Seven preceding days seed sparse states; missing seeds stay unknown. Row
    limits are explicit, not a silent claim to have covered the whole period.
    """
    end = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    start = end - int(min(168, hours) * 3600)
    floor = start - 7 * 86400
    table_name = f'device_history_{device_id}'
    table = hist.quote(table_name)
    fields = [name for name in FIELDS if name in columns]
    if not fields:
        raise ValueError('No heating or temperature readings have been recorded for this device')
    def stamp(epoch):
        return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    # Fail closed on an unsuccessful PK probe; never fall back to a table scan.
    lo = owner._rowid_for_ts(conn, table_name, stamp(floor))
    hi = owner._rowid_for_ts(conn, table_name, stamp(end + 1))
    if lo is None or hi is None:
        return {'ok': True, 'start': start, 'end': end, 'series': {}, 'truncated': False,
                'gapSeconds': GAP_SECONDS, 'deviceId': device_id}
    selected = ', '.join(hist.quote(name) for name in fields)
    rows = conn.execute(f'SELECT {hist.epoch()}, {selected} FROM {table} '
                        'WHERE id >= ? AND id < ? ORDER BY id DESC LIMIT ?',
                        (lo, hi, ROW_LIMIT + 1))
    truncated = len(rows) > ROW_LIMIT
    rows = list(reversed(rows[:ROW_LIMIT]))
    series = {name: [] for name in fields}
    seeds = {}
    for row in rows:
        if row[0] is None:
            continue
        t = int(row[0])
        if not floor <= t <= end:
            continue
        for name, raw in zip(fields, row[1:]):
            if raw is None:  # SQL Logger writes only changes.
                continue
            value = raw
            if name not in ('gatewaystatus', 'setpointsource'):
                try:
                    if name == 'hvacheaterison' and str(raw).lower() in ('true', 'false', 't', 'f'):
                        value = int(str(raw).lower() in ('true', 't'))
                    else:
                        value = float(raw)
                    if not math.isfinite(value):
                        value = None
                    if name == 'hvacheaterison' and value not in (0, 1):
                        value = None
                except (ValueError, TypeError):
                    value = None
            point = {'t': t, 'v': value}
            if t < start:
                seeds[name] = point
            else:
                series[name].append(point)
    for name, seed in seeds.items():
        series[name].insert(0, seed)
    return {'ok': True, 'deviceId': device_id, 'start': start, 'end': end,
            'series': series, 'truncated': truncated, 'gapSeconds': GAP_SECONDS}


_LINE = re.compile(r'^\[(\d{2}:\d{2}:\d{2})\.\d+\]\s+(.+?)\s{2,}(?:\?\?|[-\d.]+) -> ([-\d.]+)\s{2,}(.+)$')


def decisions(log_dir, zone_name, start, end):
    """Return this zone's recorded decisions, never raw log text or guessed causes.

    These are requested targets, not proof the controller received a command.
    A repeated autumn wall-clock hour cannot identify an instant: omit those
    entries and say so rather than putting them on the wrong hour.
    """
    result, available, ambiguous, truncated = [], False, False, False
    day = datetime.fromtimestamp(start).date()
    final = datetime.fromtimestamp(end).date()
    while day <= final:
        path = os.path.join(log_dir, f'changes_{day.isoformat()}.log')
        try:
            with open(path, 'rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                tail = max(0, size - 524288)
                truncated |= bool(tail)
                stream.seek(tail)
                if tail:
                    stream.readline()
                text = stream.read(524288).decode('utf-8', errors='replace')
            available = True
        except FileNotFoundError:
            day += timedelta(days=1)
            continue
        for line in text.splitlines():
            match = _LINE.fullmatch(line)
            if not match or match[2].strip() != zone_name:
                continue
            dt = datetime.fromisoformat(f'{day.isoformat()}T{match[1]}')
            if dt.replace(fold=0).timestamp() != dt.replace(fold=1).timestamp():
                ambiguous = True
                continue
            t = int(dt.timestamp())
            if start <= t <= end:
                # Only the established reason after the separator is exposed.
                reason = match[4].partition(' - ')[2]
                if reason:
                    result.append({'t': t, 'target': float(match[3]), 'reason': reason[:180]})
        day += timedelta(days=1)
    return {'items': result, 'available': available, 'ambiguous': ambiguous, 'truncated': truncated}
