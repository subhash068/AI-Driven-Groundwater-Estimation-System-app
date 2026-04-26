import os
import requests


GEOSERVER_URL = os.getenv("GEOSERVER_URL", "http://localhost:8080/geoserver")
GEOSERVER_USER = os.getenv("GEOSERVER_USER", "admin")
GEOSERVER_PASSWORD = os.getenv("GEOSERVER_PASSWORD", "geoserver")
WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "groundwater")
STORE = os.getenv("GEOSERVER_STORE", "groundwater_postgis")

POSTGIS_HOST = os.getenv("POSTGIS_HOST", "localhost")
POSTGIS_PORT = os.getenv("POSTGIS_PORT", "5432")
POSTGIS_DB = os.getenv("POSTGIS_DB", "groundwater")
POSTGIS_USER = os.getenv("POSTGIS_USER", "postgres")
POSTGIS_PASS = os.getenv("POSTGIS_PASS", "postgres")
POSTGIS_SCHEMA = os.getenv("POSTGIS_SCHEMA", "groundwater")


def request(method: str, endpoint: str, json_payload: dict | None = None, expected: tuple[int, ...] = (200, 201)):
    url = f"{GEOSERVER_URL}{endpoint}"
    r = requests.request(
        method,
        url,
        auth=(GEOSERVER_USER, GEOSERVER_PASSWORD),
        headers={"Content-Type": "application/json"},
        json=json_payload,
        timeout=60,
    )
    if r.status_code not in expected:
        raise RuntimeError(f"{method} {url} failed: {r.status_code} {r.text}")
    return r


def ensure_workspace():
    payload = {"workspace": {"name": WORKSPACE}}
    request("POST", "/rest/workspaces", payload, expected=(201, 401, 403, 409))


def ensure_datastore():
    payload = {
        "dataStore": {
            "name": STORE,
            "connectionParameters": {
                "entry": [
                    {"@key": "dbtype", "$": "postgis"},
                    {"@key": "host", "$": POSTGIS_HOST},
                    {"@key": "port", "$": POSTGIS_PORT},
                    {"@key": "database", "$": POSTGIS_DB},
                    {"@key": "schema", "$": POSTGIS_SCHEMA},
                    {"@key": "user", "$": POSTGIS_USER},
                    {"@key": "passwd", "$": POSTGIS_PASS},
                    {"@key": "Expose primary keys", "$": "true"},
                ]
            },
        }
    }
    request(
        "POST",
        f"/rest/workspaces/{WORKSPACE}/datastores",
        payload,
        expected=(201, 401, 403, 409),
    )


def publish_featuretype(table_name: str, title: str):
    payload = {"featureType": {"name": table_name, "nativeName": table_name, "title": title}}
    request(
        "POST",
        f"/rest/workspaces/{WORKSPACE}/datastores/{STORE}/featuretypes",
        payload,
        expected=(201, 401, 403, 409),
    )


if __name__ == "__main__":
    ensure_workspace()
    ensure_datastore()
    publish_featuretype("villages", "Village Boundaries")
    publish_featuretype("hydrogeology", "Hydrogeology")
    publish_featuretype("village_features", "Geomorphology and Terrain Features")
    publish_featuretype("rainfall_history", "Rainfall Grid")
    print("GeoServer workspace/store/layers bootstrapped. WMS/WFS endpoints are now publishable.")
