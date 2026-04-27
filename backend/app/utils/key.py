def normalize_location_name(value) -> str:
    text = (
        str(value or "")
        .strip()
        .lower()
        .replace(".", "")
    )
    return "".join(ch for ch in text if ch.isalnum())


def build_location_key(district, mandal, village_name="") -> str:
    return "|".join(
        [
            normalize_location_name(district),
            normalize_location_name(mandal),
            normalize_location_name(village_name),
        ]
    )


def make_key(district, mandal, village_name="") -> str:
    return build_location_key(district, mandal, village_name)
