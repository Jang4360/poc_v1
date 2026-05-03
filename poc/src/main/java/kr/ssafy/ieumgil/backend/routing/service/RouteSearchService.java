package kr.ssafy.ieumgil.backend.routing.service;

import kr.ssafy.ieumgil.backend.routing.client.GraphHopperRouteException;
import kr.ssafy.ieumgil.backend.routing.client.GraphHopperRoutingClient;
import kr.ssafy.ieumgil.backend.routing.client.GraphHopperClient;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;
import kr.ssafy.ieumgil.backend.routing.dto.GhPath;
import kr.ssafy.ieumgil.backend.routing.dto.GhRouteResponse;
import kr.ssafy.ieumgil.backend.routing.dto.RouteOptionResult;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchRequest;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchResponse;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class RouteSearchService {
    private final GraphHopperRoutingClient graphHopperClient;
    private final RoutingProfileResolver profileResolver;

    public RouteSearchService(GraphHopperRoutingClient graphHopperClient, RoutingProfileResolver profileResolver) {
        this.graphHopperClient = graphHopperClient;
        this.profileResolver = profileResolver;
    }

    public RouteSearchResponse search(RouteSearchRequest request) {
        List<RouteOption> options = request.routeOption() == null
                ? List.of(RouteOption.SAFE, RouteOption.SHORTEST)
                : List.of(request.routeOption());

        List<RouteOptionResult> routes = options.stream()
                .map(option -> routeOption(request, option))
                .toList();

        return new RouteSearchResponse(request.disabilityType(), request.origin(), request.destination(), routes);
    }

    private RouteOptionResult routeOption(RouteSearchRequest request, RouteOption option) {
        if (option == RouteOption.PUBLIC_TRANSPORT) {
            return RouteOptionResult.unavailable(option, null, "PUBLIC_TRANSPORT_NOT_IMPLEMENTED");
        }

        String profile = profileResolver.resolve(request.disabilityType(), option);
        try {
            GhRouteResponse response = graphHopperClient.route(
                    request.origin(),
                    request.destination(),
                    profile,
                    GraphHopperClient.WALK_DETAILS
            );
            if (response == null || response.paths() == null || response.paths().isEmpty()) {
                return RouteOptionResult.unavailable(option, profile, "NO_ACCESSIBLE_ROUTE");
            }
            GhPath path = response.paths().getFirst();
            return RouteOptionResult.available(option, profile, path);
        } catch (GraphHopperRouteException e) {
            return RouteOptionResult.unavailable(option, profile, e.reason());
        }
    }
}
