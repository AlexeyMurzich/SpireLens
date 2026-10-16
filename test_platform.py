"""Platform-specific default paths and PCK discovery, on synthetic folders only."""
from pathlib import Path
import shutil
import unittest
from unittest import mock
import uuid

from analyzer import default_root, find_pck
from desktop import config_path

GAME = 'steamapps/common/Slay the Spire 2'
MAC_PCK = GAME + '/SlayTheSpire2.app/Contents/Resources/Slay the Spire 2.pck'
WINDOWS_PCK = GAME + '/SlayTheSpire2.pck'


class PlatformPathTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(__file__).resolve().parent / '.test-work'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / ('platform-' + uuid.uuid4().hex)
        self.home = self.root / 'home'
        self.home.mkdir(parents=True)
        # Never consult the real Windows registry: tests must not see an installed game.
        patcher = mock.patch('analyzer.registry_steam_path', return_value=None)
        self.registry = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.assertEqual(self.root.resolve().parent, self.scratch.resolve())
        shutil.rmtree(self.root)

    def touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'GDPC')
        return path

    def library_vdf(self, steam, library):
        vdf = steam / 'steamapps/libraryfolders.vdf'
        vdf.parent.mkdir(parents=True, exist_ok=True)
        # Steam escapes backslashes in Windows paths.
        escaped = str(library).replace('\\', '\\\\')
        vdf.write_text(f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t}}\n}}\n', encoding='utf-8')

    def test_macos_default_history(self):
        expected = self.home / 'Library/Application Support/SlayTheSpire2'
        self.assertEqual(default_root('darwin', {}, self.home), expected)
        # A stray APPDATA variable must not redirect macOS to a Windows layout.
        self.assertEqual(default_root('darwin', {'APPDATA': str(self.root / 'roaming')}, self.home), expected)

    def test_windows_default_history_unchanged(self):
        appdata = self.root / 'Roaming'
        self.assertEqual(default_root('win32', {'APPDATA': str(appdata)}, self.home), appdata / 'SlayTheSpire2')
        self.assertEqual(default_root('win32', {}, self.home), self.home / 'AppData/Roaming/SlayTheSpire2')

    def test_macos_default_settings(self):
        expected = self.home / 'Library/Application Support/SpireLens/settings.json'
        self.assertEqual(config_path(None, 'darwin', {}, self.home), expected)
        self.assertEqual(config_path(None, 'darwin', {'LOCALAPPDATA': str(self.root / 'local')}, self.home), expected)

    def test_windows_default_settings_unchanged(self):
        local = self.root / 'Local'
        self.assertEqual(config_path(None, 'win32', {'LOCALAPPDATA': str(local)}, self.home), local / 'SpireLens/settings.json')
        self.assertEqual(config_path(None, 'win32', {}, self.home), self.home / 'SpireLens/settings.json')

    def test_config_dir_override(self):
        folder = self.root / 'custom config'
        for platform in ('darwin', 'win32'):
            with self.subTest(platform=platform):
                self.assertEqual(config_path(folder, platform, {'LOCALAPPDATA': str(self.root / 'local')}, self.home),
                                 folder / 'settings.json')

    def test_macos_pck_in_default_steam(self):
        steam = self.home / 'Library/Application Support/Steam'
        pck = self.touch(steam / MAC_PCK)
        self.assertEqual(find_pck('darwin', {}, self.home), pck)

    def test_macos_pck_in_additional_library(self):
        steam = self.home / 'Library/Application Support/Steam'
        library = self.root / 'External Drive/SteamLibrary'
        self.library_vdf(steam, library)
        pck = self.touch(library / MAC_PCK)
        self.assertEqual(find_pck('darwin', {}, self.home), pck)

    def test_macos_without_game(self):
        self.assertIsNone(find_pck('darwin', {}, self.home))

    def test_windows_pck_in_default_steam_unchanged(self):
        program_files = self.root / 'Program Files (x86)'
        pck = self.touch(program_files / 'Steam' / WINDOWS_PCK)
        self.assertEqual(find_pck('win32', {'PROGRAMFILES(X86)': str(program_files)}, self.home), pck)

    def test_windows_pck_in_additional_library_unchanged(self):
        program_files = self.root / 'Program Files (x86)'
        library = self.root / 'D/SteamLibrary'
        self.library_vdf(program_files / 'Steam', library)
        pck = self.touch(library / WINDOWS_PCK)
        self.assertEqual(find_pck('win32', {'PROGRAMFILES(X86)': str(program_files)}, self.home), pck)

    def test_windows_pck_from_registry_steam_unchanged(self):
        registry_steam = self.root / 'Registry Steam'
        pck = self.touch(registry_steam / WINDOWS_PCK)
        self.registry.return_value = registry_steam
        self.assertEqual(find_pck('win32', {'PROGRAMFILES(X86)': str(self.root / 'empty')}, self.home), pck)

    def test_windows_ignores_macos_steam(self):
        self.touch(self.home / 'Library/Application Support/Steam' / MAC_PCK)
        self.assertIsNone(find_pck('win32', {'PROGRAMFILES(X86)': str(self.root / 'empty')}, self.home))
        self.registry.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
