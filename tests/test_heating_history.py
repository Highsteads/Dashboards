#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_heating_history.py
# Description: Sparse heating history, query bounds and recorded reasons.
# Author:      CliveS & Codex GPT-6
# Date:        26-10-2026
# Version:     1.0
import os
import sqlite3
import time
from datetime import datetime, timezone

import pytest
from conftest import bare_plugin


@pytest.fixture
def history(tmp_path):
    p = bare_plugin()
    import heating_history as h
    path = tmp_path / 'history.sqlite'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE device_history_42 (id INTEGER PRIMARY KEY, ts TEXT, '
                'temperatureinput1 REAL, setpointheat REAL, hvacheaterison TEXT, temperatureseenepoch REAL)')
    now = int(time.time())
    def add(age, temp=None, target=None, call=None, seen=None):
        stamp = datetime.fromtimestamp(now-age, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        con.execute('INSERT INTO device_history_42 VALUES (NULL,?,?,?,?,?)', (stamp,temp,target,call,seen))
        con.commit()
    p._history_db_path = lambda: str(path)
    yield p, h, con, now, add
    con.close()


def test_dispatch_keeps_unaveraged_changes_and_seeds(history):
    p,h,con,now,add = history
    add(90000,18,12,'false',now-90000)
    add(600,None,22,'true',now-600)
    add(590,None,12,'false')  # ten-second call must not become 0.5
    result = p._history_query({'action':'heating','deviceId':42,'hours':24})
    assert [x['v'] for x in result['series']['setpointheat']] == [12,22,12]
    assert [x['v'] for x in result['series']['hvacheaterison']] == [0,1,0]
    assert result['series']['temperatureinput1'][0]['t'] < result['start']
    assert p._history_key({'action':'heating','deviceId':42}) != p._history_key({'deviceId':42})


def test_missing_seeds_and_invalid_values_stay_unknown(history):
    p,h,con,now,add = history
    add(200,17,None,'not known')
    result=p._history_query({'action':'heating','deviceId':42})
    assert result['series']['setpointheat'] == []
    assert result['series']['hvacheaterison'][0]['v'] is None


def test_row_cap_is_explicit_and_no_writes(history, monkeypatch):
    p,h,con,now,add=history
    for age in [600,500,400,300]: add(age,18)
    monkeypatch.setattr(h,'ROW_LIMIT',2)
    before = con.total_changes
    result=p._history_query({'action':'heating','deviceId':42})
    assert result['truncated']
    assert len(result['series']['temperatureinput1'])==2
    assert con.total_changes==before


def test_query_is_pk_bounded_and_never_falls_back_to_scan(history):
    p,h,con,now,add=history
    add(50,18)
    hist=p._history(); db=hist.connect()
    statements=[]
    original=db.execute
    def record(sql,args=()):
        statements.append(sql)
        return original(sql,args)
    db.execute=record
    try:
        h.read_history(p,hist,db,42,{'temperatureinput1'},24,now)
    finally: db.close()
    sql=next(s for s in statements if 'LIMIT ?' in s)
    assert 'id >= ? AND id < ?' in sql
    plan=con.execute('EXPLAIN QUERY PLAN '+sql,(1,10,30001)).fetchall()
    assert any('INTEGER PRIMARY KEY' in r[3] for r in plan)
    p._rowid_for_ts=lambda *a: (_ for _ in ()).throw(RuntimeError('probe failed'))
    with pytest.raises(RuntimeError): p._history_query({'action':'heating','deviceId':42})


def test_decisions_are_exact_zone_matches_and_requests_only(tmp_path):
    bare_plugin()
    import heating_history as h
    day=datetime.now().strftime('%Y-%m-%d')
    (tmp_path/f'changes_{day}.log').write_text(
        '[12:00:00.123] Hall                  12.0 -> 22.0  Raised to 22degC - Boost mode active\n'
        '[12:00:01.123] Hall Kitchen          12.0 -> 18.0  Raised to 18degC - Schedule step up\n'
        'unstructured text should never be returned\n',encoding='utf-8')
    start=datetime.fromisoformat(day).timestamp()
    result=h.decisions(str(tmp_path),'Hall',start,start+86400)
    assert result['available']
    assert len(result['items'])==1
    assert result['items'][0]['reason']=='Boost mode active'
    assert h.decisions(str(tmp_path),'missing',start,start+86400)['items']==[]


def test_ambiguous_autumn_reason_is_not_given_a_false_time(tmp_path):
    bare_plugin()
    import heating_history as h
    before=os.environ.get('TZ')
    try:
        os.environ['TZ']='Europe/London'; time.tzset()
        (tmp_path/'changes_2026-10-25.log').write_text('[01:30:00.123] Hall                  12.0 -> 22.0  Raised to 22degC - Boost mode active\n')
        a=datetime(2026,10,25).timestamp(); b=datetime(2026,10,26).timestamp()
        result=h.decisions(str(tmp_path),'Hall',a,b)
        assert result['ambiguous'] and result['items']==[]
    finally:
        if before is None: os.environ.pop('TZ',None)
        else: os.environ['TZ']=before
        time.tzset()
