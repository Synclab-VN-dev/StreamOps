"""Fixture-level Windows library discovery: no real Steam or games used."""
from streamops.server.platform.windows.game_process import WindowsGameProcess
from streamops.server.services.games.providers.static import StaticProvider

class FakeSteamInstall:
    def __init__(self, exe):
        self.exe=exe
    def resolve_installation(self, *, required=False):
        return self.exe

def test_primary_steam_library_manifest(tmp_path):
    root=tmp_path/"Steam"
    root.mkdir()
    game=StaticProvider().discover()[0]
    folder=root/"steamapps"/"common"/"Diablo IV"
    folder.mkdir(parents=True)
    (root/"steamapps"/"appmanifest_2344520.acf").write_text('"AppState" { "installdir" "Diablo IV" }',encoding="utf-8")
    assert WindowsGameProcess(FakeSteamInstall(root/"steam.exe"))._installed_dir(game)==folder.resolve()

def test_secondary_steam_library_manifest(tmp_path):
    root=tmp_path/"Steam"
    steamapps=root/"steamapps"
    steamapps.mkdir(parents=True)
    secondary=tmp_path/"SecondLibrary"
    folder=secondary/"steamapps"/"common"/"Diablo IV"
    folder.mkdir(parents=True)
    (secondary/"steamapps"/"appmanifest_2344520.acf").write_text('"installdir" "Diablo IV"',encoding="utf-8")
    escaped=str(secondary).replace(chr(92),chr(92)*2)
    (steamapps/"libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path" "'+escaped+'" } }',encoding="utf-8")
    game=StaticProvider().discover()[0]
    assert WindowsGameProcess(FakeSteamInstall(root/"steam.exe"))._installed_dir(game)==folder.resolve()

def test_malicious_install_dir_is_not_trusted(tmp_path):
    root=tmp_path/"Steam"
    steamapps=root/"steamapps"
    steamapps.mkdir(parents=True)
    (steamapps/"appmanifest_2344520.acf").write_text('"installdir" "../other"',encoding="utf-8")
    game=StaticProvider().discover()[0]
    assert WindowsGameProcess(FakeSteamInstall(root/"steam.exe"))._installed_dir(game) is None
