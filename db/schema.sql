CREATE EXTENSION IF NOT EXISTS postgis;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'yes_no_unknown') THEN
        CREATE TYPE yes_no_unknown AS ENUM ('YES', 'NO', 'UNKNOWN');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'width_state') THEN
        CREATE TYPE width_state AS ENUM ('ADEQUATE_150', 'ADEQUATE_120', 'NARROW', 'UNKNOWN');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'crossing_state') THEN
        CREATE TYPE crossing_state AS ENUM ('TRAFFIC_SIGNALS', 'NO', 'UNKNOWN');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS places (
    "placeId" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "name" VARCHAR(200) NOT NULL,
    "category" VARCHAR(80) NOT NULL,
    "address" TEXT,
    "point" GEOMETRY(POINT, 4326) NOT NULL,
    "providerPlaceId" VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_places_point ON places USING GIST ("point");
CREATE INDEX IF NOT EXISTS idx_places_category ON places ("category");
CREATE UNIQUE INDEX IF NOT EXISTS uq_places_provider_place_id
    ON places ("providerPlaceId")
    WHERE "providerPlaceId" IS NOT NULL;

CREATE TABLE IF NOT EXISTS place_accessibility_features (
    "id" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "placeId" INTEGER NOT NULL REFERENCES places ("placeId") ON DELETE CASCADE,
    "featureType" VARCHAR(80) NOT NULL,
    "isAvailable" BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_place_accessibility_features_place_id
    ON place_accessibility_features ("placeId");
CREATE UNIQUE INDEX IF NOT EXISTS uq_place_accessibility_features_place_feature
    ON place_accessibility_features ("placeId", "featureType");

CREATE TABLE IF NOT EXISTS road_nodes (
    "vertexId" BIGINT PRIMARY KEY,
    "sourceNodeKey" VARCHAR(100) NOT NULL UNIQUE,
    "point" GEOMETRY(POINT, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_road_nodes_point ON road_nodes USING GIST ("point");

CREATE TABLE IF NOT EXISTS road_segments (
    "edgeId" BIGINT PRIMARY KEY,
    "fromNodeId" BIGINT NOT NULL REFERENCES road_nodes ("vertexId"),
    "toNodeId" BIGINT NOT NULL REFERENCES road_nodes ("vertexId"),
    "geom" GEOMETRY(LINESTRING, 4326) NOT NULL,
    "lengthMeter" NUMERIC(10, 2) NOT NULL,
    "walkAccess" VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    "avgSlopePercent" NUMERIC(6, 2),
    "widthMeter" NUMERIC(6, 2),
    "brailleBlockState" yes_no_unknown NOT NULL DEFAULT 'UNKNOWN',
    "audioSignalState" yes_no_unknown NOT NULL DEFAULT 'UNKNOWN',
    "rampState" yes_no_unknown NOT NULL DEFAULT 'UNKNOWN',
    "widthState" width_state NOT NULL DEFAULT 'UNKNOWN',
    "surfaceState" VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    "stairsState" yes_no_unknown NOT NULL DEFAULT 'UNKNOWN',
    "elevatorState" yes_no_unknown NOT NULL DEFAULT 'UNKNOWN',
    "crossingState" crossing_state NOT NULL DEFAULT 'UNKNOWN'
);

CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON road_segments USING GIST ("geom");
CREATE INDEX IF NOT EXISTS idx_road_segments_nodes ON road_segments ("fromNodeId", "toNodeId");

CREATE TABLE IF NOT EXISTS segment_features (
    "featureId" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "edgeId" BIGINT NOT NULL REFERENCES road_segments ("edgeId") ON DELETE CASCADE,
    "featureType" VARCHAR(50) NOT NULL,
    "geom" GEOMETRY(GEOMETRY, 4326) NOT NULL,
    "sourceDataset" VARCHAR(160),
    "sourceLayer" VARCHAR(80),
    "sourceRowNumber" INTEGER,
    "matchStatus" VARCHAR(30) NOT NULL DEFAULT 'MATCHED',
    "matchScore" NUMERIC(10, 6),
    "properties" JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_segment_features_edge_id ON segment_features ("edgeId");
CREATE INDEX IF NOT EXISTS idx_segment_features_type ON segment_features ("featureType");
CREATE INDEX IF NOT EXISTS idx_segment_features_geom ON segment_features USING GIST ("geom");
CREATE INDEX IF NOT EXISTS idx_segment_features_source
    ON segment_features ("sourceDataset", "sourceLayer", "sourceRowNumber");

CREATE TABLE IF NOT EXISTS road_segment_filter_polygons (
    "edgeId" BIGINT PRIMARY KEY REFERENCES road_segments ("edgeId") ON DELETE CASCADE,
    "sourceRowNumber" INTEGER NOT NULL,
    "sourceUfid" VARCHAR(34),
    "roadWidthMeter" NUMERIC(8, 2) NOT NULL,
    "bufferHalfWidthMeter" NUMERIC(8, 2) NOT NULL,
    "geom" GEOMETRY(MULTIPOLYGON, 5179) NOT NULL,
    "createdAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_road_segment_filter_polygons_geom
    ON road_segment_filter_polygons USING GIST ("geom");
CREATE INDEX IF NOT EXISTS idx_road_segment_filter_polygons_source_ufid
    ON road_segment_filter_polygons ("sourceUfid");

CREATE TABLE IF NOT EXISTS low_floor_bus_routes (
    "routeId" VARCHAR(20) PRIMARY KEY,
    "routeNo" VARCHAR(20) NOT NULL,
    "hasLowFloor" BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_low_floor_bus_routes_route_no
    ON low_floor_bus_routes ("routeNo");

CREATE TABLE IF NOT EXISTS subway_station_elevators (
    "elevatorId" INTEGER PRIMARY KEY,
    "stationId" VARCHAR(50) NOT NULL,
    "stationName" VARCHAR(100) NOT NULL,
    "lineName" VARCHAR(50) NOT NULL,
    "entranceNo" VARCHAR(50),
    "point" GEOMETRY(POINT, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subway_station_elevators_point
    ON subway_station_elevators USING GIST ("point");
CREATE INDEX IF NOT EXISTS idx_subway_station_elevators_station
    ON subway_station_elevators ("stationId", "entranceNo");
