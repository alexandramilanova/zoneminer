"""Lossless zone drafts until shared domain validation has checked names."""

from pydantic import BaseModel


class ZoneDraft(BaseModel):
    name: str
    places: list[str]


class ZoneConfiguration(BaseModel):
    # Retain the mapping contract for existing clients; lists preserve duplicate
    # and blank names from editors instead of silently overwriting them.
    zones: dict[str, list[str]] | list[ZoneDraft]

    def zone_inputs(self) -> list[tuple[str, list[str]]]:
        if isinstance(self.zones, dict):
            return list(self.zones.items())
        return [(draft.name, draft.places) for draft in self.zones]
