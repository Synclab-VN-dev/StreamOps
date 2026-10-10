"""G6: assert that the static provider seed is discoverable as package data."""
from importlib.resources import files
import json
from streamops.server.services.games.providers.static import StaticProvider

def test_games_seed_resource():
    seed=files("streamops.server").joinpath("data/games.seed.json")
    assert seed.is_file()
    assert json.loads(seed.read_text(encoding="utf-8"))["schemaVersion"]==1
    assert StaticProvider().discover()[0].id=="steam:2344520"
