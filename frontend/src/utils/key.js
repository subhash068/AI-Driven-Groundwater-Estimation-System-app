function normalizeKeyPart(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\./g, "")
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9]+/g, "");
}

export function buildDistrictVillageKey(district, mandal, villageName = "") {
  return [district, mandal, villageName].map(normalizeKeyPart).join("|");
}

export function buildMandalVillageKey(mandal, villageName = "") {
  return [mandal, villageName].map(normalizeKeyPart).join("|");
}

export const makeKey = buildDistrictVillageKey;

export function getDistrictVillageKeyFromRecord(record) {
  if (!record) return "";
  return buildDistrictVillageKey(
    record.district ?? record.District,
    record.mandal ?? record.Mandal,
    record.village_name ?? record.Village_Name ?? record.village ?? record.name
  );
}

export function normalizeDistrictVillageKeyPart(value) {
  return normalizeKeyPart(value);
}
