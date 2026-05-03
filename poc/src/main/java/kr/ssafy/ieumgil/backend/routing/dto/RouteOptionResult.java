package kr.ssafy.ieumgil.backend.routing.dto;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;

import java.util.List;
import java.util.Map;

public record RouteOptionResult(
        RouteOption routeOption,
        String graphhopperProfile,
        boolean available,
        String reason,
        RouteSummary summary,
        JsonNode geometry,
        boolean pointsEncoded,
        List<GhInstruction> instructions,
        Map<String, JsonNode> details
) {
    public static RouteOptionResult available(RouteOption routeOption, String profile, GhPath path) {
        return new RouteOptionResult(
                routeOption,
                profile,
                true,
                null,
                new RouteSummary(path.distance(), path.time(), path.weight()),
                path.points(),
                path.points_encoded(),
                path.instructions() == null ? List.of() : path.instructions(),
                path.details() == null ? Map.of() : path.details()
        );
    }

    public static RouteOptionResult unavailable(RouteOption routeOption, String profile, String reason) {
        return new RouteOptionResult(routeOption, profile, false, reason, null, null, false, List.of(), Map.of());
    }
}
