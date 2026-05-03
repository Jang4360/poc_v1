# GraphHopper Plugin

This directory is the Java/Maven execution boundary for the Gangseo EumGil GraphHopper integration.

Runtime data, Docker files, GraphHopper config, PBF, and graph-cache stay under the root
`graphhopper/` and `docker/graphhopper/` directories. This module only owns Java code:

- `IeumImportRegistry`: delegates standard GraphHopper import units and adds EumGil custom units.
- `IeumEncodedValues`: custom EV names used by `graphhopper/config.yml` and custom models.
- `IeumEnumTagParser` / `IeumDecimalTagParser`: read `ieum:*` OSM way tags.
- `IeumGraphHopperApplication`: starts GraphHopper with the custom import registry.

Canonical profiles:

- `pedestrian_safe`
- `pedestrian_fast`
- `visual_safe`
- `visual_fast`
- `wheelchair_manual_safe`
- `wheelchair_manual_fast`
- `wheelchair_auto_safe`
- `wheelchair_auto_fast`

Run:

```bash
mvn -f graphhopper-plugin/pom.xml test
```
