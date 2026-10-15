import json
from pathlib import Path
import shutil
import unittest
import uuid

from desktop import load_config, save_config, export_runs
from analyzer import Store
from test_analyzer import sample, ACCOUNT


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.scratch=Path(__file__).resolve().parent/'.test-work'
        self.scratch.mkdir(parents=True,exist_ok=True)
        self.root=self.scratch/('desktop-'+uuid.uuid4().hex);self.root.mkdir()

    def tearDown(self):
        self.assertEqual(self.root.resolve().parent,self.scratch.resolve())
        shutil.rmtree(self.root)

    def test_settings_missing_invalid_and_persisted(self):
        path=self.root/'settings.json'
        self.assertEqual(load_config(path),{})
        path.write_text('{')
        self.assertEqual(load_config(path),{})
        values={'data_dir':str(self.root/'Мои забеги'),'pck':'D:/Games/SlayTheSpire2.pck'}
        save_config(path,values)
        self.assertEqual(load_config(path),values)
        self.assertFalse(path.with_suffix('.tmp').exists())

    def test_export_preserves_filters_and_does_not_change_history(self):
        history=self.root/'steam'/ACCOUNT/'profile1/saves/history';history.mkdir(parents=True)
        source=history/'test.run';source.write_text(json.dumps(sample()))
        original=source.read_bytes();store=Store(self.root);store.refresh()
        export_runs(store,{'outcome':'win'},self.root/'wins.csv')
        self.assertEqual(len((self.root/'wins.csv').read_text(encoding='utf-8-sig').splitlines()),1)
        export_runs(store,{},self.root/'all.csv')
        self.assertEqual(len((self.root/'all.csv').read_text(encoding='utf-8-sig').splitlines()),2)
        self.assertEqual(source.read_bytes(),original)


if __name__=='__main__':unittest.main()
