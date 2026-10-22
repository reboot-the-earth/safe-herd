"""Canonical species list for Safeherd v1."""

from enum import StrEnum


class Species(StrEnum):
    HORSES = "horses"
    MINIATURE_HORSES = "miniature_horses"
    MULES = "mules"
    DONKEYS = "donkeys"
    CATTLE = "cattle"
    CATTLE_CALVES = "cattle_calves"
    GOATS = "goats"
    SHEEP = "sheep"
    PIGS = "pigs"
    POULTRY = "poultry"


ALL_SPECIES: list[str] = [s.value for s in Species]
