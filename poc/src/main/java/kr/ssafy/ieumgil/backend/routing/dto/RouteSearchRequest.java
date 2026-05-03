package kr.ssafy.ieumgil.backend.routing.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import kr.ssafy.ieumgil.backend.routing.domain.DisabilityType;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;

public record RouteSearchRequest(
        @NotNull DisabilityType disabilityType,
        @JsonAlias({"mode", "routeMode"}) RouteOption routeOption,
        @NotNull @Valid @JsonAlias({"origin", "start", "startPoint"}) GeoPoint origin,
        @NotNull @Valid @JsonAlias({"destination", "end", "endPoint"}) GeoPoint destination
) {
}
