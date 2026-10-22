"""Tests for the canonical species list."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contracts.species import Species, ALL_SPECIES


def test_species_count():
    assert len(Species) == 10


def test_all_species_matches_enum():
    assert ALL_SPECIES == [s.value for s in Species]


def test_cattle_calves_is_a_species():
    assert "cattle_calves" in ALL_SPECIES
    assert Species.CATTLE_CALVES == "cattle_calves"


def test_species_are_lowercase_with_underscores():
    for s in ALL_SPECIES:
        assert s == s.lower()
        assert " " not in s
