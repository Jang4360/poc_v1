package kr.ssafy.ieumgil.backend.routing.service;

import kr.ssafy.ieumgil.backend.routing.domain.DisabilityType;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;
import org.springframework.stereotype.Component;

import java.util.Map;

@Component
public class RoutingProfileResolver {
    private static final Map<DisabilityType, Map<RouteOption, String>> PROFILE_MAP = Map.of(
            DisabilityType.VISUAL, Map.of(
                    RouteOption.SAFE, "visual_safe",
                    RouteOption.SHORTEST, "visual_fast"
            ),
            DisabilityType.MOBILITY, Map.of(
                    RouteOption.SAFE, "wheelchair_manual_safe",
                    RouteOption.SHORTEST, "wheelchair_manual_fast"
            )
    );

    public String resolve(DisabilityType disabilityType, RouteOption routeOption) {
        String profile = PROFILE_MAP.getOrDefault(disabilityType, Map.of()).get(routeOption);
        if (profile == null) {
            throw new IllegalArgumentException("No GraphHopper profile for type=%s option=%s".formatted(disabilityType, routeOption));
        }
        return profile;
    }
}
