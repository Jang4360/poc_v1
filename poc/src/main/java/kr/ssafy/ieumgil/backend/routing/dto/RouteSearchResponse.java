package kr.ssafy.ieumgil.backend.routing.dto;

import kr.ssafy.ieumgil.backend.routing.domain.DisabilityType;

import java.util.List;

public record RouteSearchResponse(
        DisabilityType disabilityType,
        GeoPoint origin,
        GeoPoint destination,
        List<RouteOptionResult> routes
) {
}
