"""UNIT-02/03 and G2/G3: same normalized provider contract, unsafe merge rejection."""
from __future__ import annotations
import copy
import pytest
from pydantic import ValidationError
from streamops.server.services.games.models import GameDefinition
from streamops.server.services.games.catalog import GameCatalogService
from streamops.server.services.games.providers.static import StaticProvider

GAME = StaticProvider().discover()[0]

class FakeSteamLocalProvider:
    def __init__(self, raw=None):
        self.raw = [GAME] if raw is None else raw
    def discover(self):
        return copy.deepcopy(self.raw)

@pytest.mark.parametrize("provider", [StaticProvider(), FakeSteamLocalProvider()])
def test_provider_contract_canonical_identity(provider):
    records = [GameDefinition.model_validate(x) for x in provider.discover()]
    assert [(r.id,r.provider,r.providerGameId) for r in records] == [("steam:2344520","steam","2344520")]
    assert records[0].stop.forceAllowed is False

@pytest.mark.parametrize("raw", [
    [GAME.model_dump() | {"enabled": "definitely"}],
    [GAME.model_dump() | {"providerGameId": "0"}],
    [GAME.model_dump() | {"untrusted_script": "taskkill"}],
    [GAME.model_dump(), GAME.model_dump()],
    "not a provider record collection",
])
def test_invalid_optional_provider_cannot_authorize_mutations(raw):
    catalog = GameCatalogService(discovery=FakeSteamLocalProvider(raw), mode="merged")
    assert catalog.refresh()[0].id == GAME.id
    assert catalog.conflicts[GAME.id] == "provider_unavailable"
    assert catalog.list()[0].launch == GAME.launch
    assert catalog.list()[0].stop == GAME.stop

@pytest.mark.parametrize("mode", ["static","shadow","merged"])
def test_provider_empty_falls_back_safely(mode):
    catalog = GameCatalogService(discovery=FakeSteamLocalProvider([]), mode=mode)
    assert catalog.refresh()[0].id == GAME.id
    assert catalog.list()[0].metadataSource == "static"

@pytest.mark.parametrize("mode", ["static","shadow","merged"])
def test_external_identity_cannot_override_static_policy(mode):
    proposed = GAME.model_copy(update={"stop":GAME.stop.model_copy(update={"forceAllowed": True})})
    catalog = GameCatalogService(discovery=FakeSteamLocalProvider([proposed]), mode=mode)
    assert catalog.refresh()[0].stop.forceAllowed is False
    if mode == "merged":
        assert catalog.conflicts[GAME.id] == "provider_identity_conflict"

def test_metadata_enrichment_only_under_merged_and_rollback():
    external = GAME.model_copy(update={"name":"Diablo 4 local"})
    for mode in ("static","shadow"):
        assert GameCatalogService(discovery=FakeSteamLocalProvider([external]),mode=mode).refresh()[0].name == GAME.name
    catalog = GameCatalogService(discovery=FakeSteamLocalProvider([external]),mode="merged")
    assert catalog.refresh()[0].name == "Diablo 4 local"
    assert catalog.list()[0].enabled == GAME.enabled
    assert catalog.list()[0].launch == GAME.launch
    assert catalog.list()[0].detection == GAME.detection
    catalog.mode = "static"
    assert catalog.refresh()[0].name == GAME.name
    assert catalog.refresh()[0].id == GAME.id

def test_owned_installed_running_remain_independent_of_discovery():
    catalog = GameCatalogService(discovery=FakeSteamLocalProvider([GAME]),mode="merged")
    definition=catalog.refresh()[0]
    assert not hasattr(definition,"owned")
    assert not hasattr(definition,"installed")
    assert not hasattr(definition,"process")

def test_duplicate_static_provider_fails_closed():
    with pytest.raises(ValueError,match="duplicate"):
        GameCatalogService(static=FakeSteamLocalProvider([GAME,GAME])).refresh()
