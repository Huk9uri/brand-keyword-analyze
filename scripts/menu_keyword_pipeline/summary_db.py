"""LLM 산출물 SQLite 저장. 영업 원본 DB와 분리한 로컬 결과 저장소."""
import hashlib
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)


class SummaryDB:
    def __init__(self,root):
        self.root=Path(root)
        self.path=self.root.parent/'llm-results.sqlite3'
        self.conn=sqlite3.connect(self.path,timeout=30)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, source_path TEXT, status TEXT, metadata TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS summaries(run_id TEXT, store_code TEXT, input_hash TEXT, result TEXT, packet TEXT, receipt TEXT, markdown TEXT,
          PRIMARY KEY(run_id,store_code));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT,store_code TEXT,status TEXT,detail TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS overviews(run_id TEXT PRIMARY KEY,aggregate_json TEXT,result TEXT,receipt TEXT,markdown TEXT);
        ''')
        from .recommendation import INSTRUCTIONS,SCHEMA
        digest=hashlib.sha256()
        digest.update(str(self.root.resolve()).encode())
        for name in ('status.json','results.json','quality.json','changes.json','registry.json','sales.json','unmapped-menus.json','observations.json'):
            path=self.root/name
            if path.exists():digest.update(name.encode()+path.read_bytes())
        digest.update((INSTRUCTIONS+encode(SCHEMA)).encode())
        self.run_id=digest.hexdigest()

    def now(self):return datetime.now(timezone.utc).isoformat()

    def state(self,status,metadata):
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)',
                (self.run_id,str(self.root.resolve()),status,encode(metadata),self.now()))

    def event(self,code,status,detail):
        with self.conn:self.conn.execute('INSERT INTO events(run_id,store_code,status,detail,created_at) VALUES(?,?,?,?,?)',
            (self.run_id,code,status,encode(detail),self.now()))

    def save_store(self,code,folder,receipt):
        def read(name):return json.loads((folder/name).read_text(encoding='utf-8'))
        result=read('summary.json');packet=read('summary-input.json')
        from .recommendation import validate
        validate(result,packet)
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?,?,?,?,?)',
                (self.run_id,code,receipt['input_hash'],encode(result),encode(packet),encode(receipt),(folder/'summary.md').read_text(encoding='utf-8')))

    def stores(self):
        return [(code,json.loads(result),json.loads(packet)) for code,result,packet in
                self.conn.execute('SELECT store_code,result,packet FROM summaries WHERE run_id=? ORDER BY store_code',(self.run_id,))]

    def save_overview(self,aggregate,result,receipt,markdown):
        with self.conn:self.conn.execute('INSERT OR REPLACE INTO overviews VALUES(?,?,?,?,?)',
            (self.run_id,encode(aggregate),encode(result),encode(receipt),markdown))

    def close(self):self.conn.close()
