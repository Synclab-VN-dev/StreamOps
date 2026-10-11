import pytest
from pydantic import ValidationError
from streamops.server.services.games.models import Seed, GameDefinition
from streamops.server.services.games.catalog import GameCatalogService
from streamops.server.services.games.providers.static import StaticProvider

def test_seed_is_packaged_and_strict():
    games = StaticProvider().discover()
    assert len(games) == 1
    assert games[0].id == "steam:2344520"
    assert games[0].stop.forceAllowed is False

@pytest.mark.parametrize("mutation", [
    lambda x: x.update(schemaVersion=2),
    lambda x: x.update(extra=True),
    lambda x: x["games"].append(dict(x["games"][0])),
    lambda x: x["games"][0].update(id="steam:123"),
    lambda x: x["games"][0].update(owned=True),
    lambda x: x["games"][0]["detection"].update(processNames=["C:/fake.exe"]),
])
def test_invalid_seed_rejected(mutation):
    import copy
    seed = {"schemaVersion": 1, "games": [StaticProvider().discover()[0].model_dump()]}
    seed = copy.deepcopy(seed)
    mutation(seed)
    with pytest.raises(ValidationError):
        StaticProvider(seed=seed).discover()

class FakeSteamLocalProvider:
    def __init__(self, changes=None):
        self.changes = changes or {}
    def discover(self):
        original = StaticProvider().discover()[0]
        return [original.model_copy(update=self.changes)]

@pytest.mark.parametrize("provider", [StaticProvider(), FakeSteamLocalProvider()])
def test_same_canonical_provider_contract(provider):
    assert [g.id for g in provider.discover()] == ["steam:2344520"]

def test_shadow_merge_and_static_rollback():
    discovered = FakeSteamLocalProvider({"name": "Diablo 4"})
    static = GameCatalogService(discovery=discovered, mode="static")
    shadow = GameCatalogService(discovery=discovered, mode="shadow")
    merged = GameCatalogService(discovery=discovered, mode="merged")
    assert static.refresh()[0].name == shadow.refresh()[0].name == "Diablo IV"
    record = merged.refresh()[0]
    assert record.name == "Diablo 4"
    assert record.id == "steam:2344520"
    assert record.launch == static.list()[0].launch
    assert record.stop == static.list()[0].stop
    assert GameCatalogService(mode="static").refresh()[0].name == "Diablo IV"

def test_unavailable_provider_falls_back_without_crash():
    class Failing:
        def discover(self):
            raise RuntimeError("no manifest")
    catalog = GameCatalogService(discovery=Failing(), mode="merged")
    assert catalog.refresh()[0].id == "steam:2344520"
    assert catalog.conflicts["steam:2344520"] == "provider_unavailable"
