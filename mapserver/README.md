# MapServer Alternative

`groundwater.map` provides a MapServer-based WMS/WFS alternative to GeoServer.

## Use

1. Install MapServer with PostGIS support.
2. Copy `mapserver/groundwater.map` into your mapfile directory.
3. Update PostGIS credentials in the `CONNECTION` strings.
4. Publish through your CGI/MapServer endpoint.

Layers included:
- villages
- hydrogeology permeability
