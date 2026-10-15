import copy
import json
from pathlib import Path
import shutil
import uuid
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

from analyzer import Store, normalize
from app import make_handler, csv_cell

ACCOUNT = '76561198000000001'  # Synthetic fixture ID; not a real user's profile.


def sample():
    return dict(start_time=1791995943, run_time=700, seed='ABC', ascension=10,
        build_id='v0.111.0', game_mode='standard', win=False, was_abandoned=True,
        killed_by_encounter='ENCOUNTER.BOSS', players=[dict(id=1, character='CHARACTER.SILENT',
        deck=[{'id':'CARD.FOOTWORK'}], relics=[], potions=[{'id':'POTION.ENERGY'}])],
        map_point_history=[[dict(map_point_type='boss', rooms=[dict(model_id='ENCOUNTER.BOSS',room_type='boss',turns_taken=3)],
        player_stats=[dict(player_id=1,current_hp=0,max_hp=70,damage_taken=25,
        card_choices=[dict(card={'id':'CARD.FOOTWORK'},was_picked=True)])])]])


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent / '.test-work'
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / ('case-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.history = self.root/'steam'/ACCOUNT/'profile1/saves/history'
        self.history.mkdir(parents=True)

    def tearDown(self):
        expected = Path(__file__).resolve().parent / '.test-work'
        self.assertEqual(self.root.resolve().parent, expected.resolve())
        shutil.rmtree(self.root)

    def write(self, d, name='1.run'):
        p=self.history/name
        p.write_text(json.dumps(d),encoding='utf-8')
        return p

    def test_death_takes_precedence_over_abandoned(self):
        r=normalize(sample(),self.history/'1.run',self.root)
        self.assertEqual(r['outcome'],'loss')
        self.assertTrue(r['abandoned'])

    def test_exit_and_win(self):
        d=sample();d['killed_by_encounter']='NONE.NONE';d['map_point_history'][0][0]['player_stats'][0]['current_hp']=50
        self.assertEqual(normalize(d,self.history/'1.run',self.root)['outcome'],'abandoned')
        d['win']=True
        self.assertEqual(normalize(d,self.history/'1.run',self.root)['outcome'],'win')

    def test_neow_restart_is_not_a_death(self):
        d=sample();d['killed_by_encounter']='NONE.NONE';d['killed_by_event']='EVENT.NEOW'
        d['map_point_history'][0][0]['player_stats'][0]['max_hp']=0
        self.assertEqual(normalize(d,self.history/'1.run',self.root)['outcome'],'abandoned')

    def test_cause_with_positive_hp_does_not_prove_death(self):
        d=sample();d['map_point_history'][0][0]['player_stats'][0]['current_hp']=19
        self.assertEqual(normalize(d,self.history/'1.run',self.root)['outcome'],'abandoned')
        d['map_point_history'][0][0]['player_stats'][0]['max_hp']=70
        self.assertEqual(normalize(d,self.history/'1.run',self.root)['outcome'],'abandoned')

    def test_coop_owner_is_selected_not_first_player(self):
        d=sample();own=copy.deepcopy(d['players'][0]);own['id']=int(ACCOUNT)
        d['players'][0]['id']=999;d['players'][0]['character']='CHARACTER.REGENT';d['players'].append(own)
        d['map_point_history'][0][0]['player_stats']=[dict(player_id=999,damage_taken=200),dict(player_id=int(ACCOUNT),damage_taken=7,current_hp=0)]
        r=normalize(d,self.history/'1.run',self.root)
        self.assertEqual(r['damage'],7);self.assertEqual(r['character'],'CHARACTER.SILENT')
        d['players'][1]['id']=888
        with self.assertRaises(ValueError):normalize(d,self.history/'1.run',self.root)

    def test_refresh_deduplicates_and_retries_invalid_files(self):
        self.write(sample());self.write(sample(),'copy.run');bad=self.history/'bad.run';bad.write_text('{')
        self.write(sample(),'ignored.run.backup')
        s=Store(self.root);s.refresh()
        self.assertEqual(len(s.runs),1);self.assertEqual(len(s.errors),1)
        d=sample();d['start_time']+=100;d['seed']='OTHER';bad.write_text(json.dumps(d))
        s.refresh();self.assertEqual(len(s.runs),2);self.assertEqual(s.errors,[])
        bad.unlink();s.refresh();self.assertEqual(len(s.runs),1)

    def test_card_choices_count_once_per_run_and_filters(self):
        d=sample();d['map_point_history'][0].append(copy.deepcopy(d['map_point_history'][0][0]));self.write(d)
        w=sample();w['start_time']+=5;w['seed']='WIN';w['win']=True;w['was_abandoned']=False;self.write(w,'2.run')
        s=Store(self.root);s.refresh();a=s.analysis({})
        self.assertEqual(a['summary']['rate'],50);self.assertEqual(a['cards'][0]['offered'],2)
        self.assertEqual(a['cards'][0]['picked'],2);self.assertEqual(a['cards'][0]['rate'],50)
        self.assertEqual(len(s.select({'exclude_abandoned':['1']})),1)
        self.assertEqual(len(s.select({'outcome':['finished']})),2)
        self.assertEqual(len(s.select({'party':['coop']})),0)
        self.assertEqual(s.detail(s.runs[0]['id'])['nodes'][0]['damage'],25)

    def test_http_and_csv(self):
        self.write(sample());s=Store(self.root);s.refresh()
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(s))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/analysis') as r:self.assertEqual(json.load(r)['summary']['count'],1)
            with urlopen(base+'/api/export.csv') as r:self.assertTrue(r.read().startswith(b'\xef\xbb\xbf'))
            with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/meta',headers={'Host':'evil.example'}))
            self.assertEqual(e.exception.code,403)
            e.exception.close()
            with self.assertRaises(HTTPError) as e:urlopen(base+'/api/run/missing')
            e.exception.close()
            with self.assertRaises(HTTPError) as e:urlopen(base+'/api/analysis?ascension=bad')
            e.exception.close()
        finally:
            server.shutdown();server.server_close()
        self.assertEqual(csv_cell('=HYPERLINK(1)'),"'=HYPERLINK(1)")


if __name__ == '__main__':
    unittest.main()
