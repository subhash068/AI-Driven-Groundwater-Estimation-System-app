# GeoServer WMS/WFS Setup

This folder provides a bootstrap script to expose groundwater layers through WMS/WFS.

## Prerequisites

1. GeoServer is running (default: `http://localhost:8080/geoserver`).
2. PostGIS schema `groundwater` is initialized.
3. Environment variables are configured (or defaults used).

## Bootstrap

```bash
python geoserver/bootstrap_geoserver.py
```

## Environment Variables

- `GEOSERVER_URL`
- `GEOSERVER_USER`
- `GEOSERVER_PASSWORD`
- `GEOSERVER_WORKSPACE`
- `GEOSERVER_STORE`
- `POSTGIS_HOST`
- `POSTGIS_PORT`
- `POSTGIS_DB`
- `POSTGIS_USER`
- `POSTGIS_PASS`
- `POSTGIS_SCHEMA`

## Published Layers

- `groundwater:villages`
- `groundwater:hydrogeology`
- `groundwater:village_features`
- `groundwater:rainfall_history`

These are available through WMS/WFS once published by the script.
