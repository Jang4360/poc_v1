package kr.ssafy.ieumgil.backend.routing.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ssafy.ieumgil.backend.routing.client.GraphHopperRouteException;
import kr.ssafy.ieumgil.backend.routing.client.GraphHopperRoutingClient;
import kr.ssafy.ieumgil.backend.routing.domain.DisabilityType;
import kr.ssafy.ieumgil.backend.routing.domain.RouteOption;
import kr.ssafy.ieumgil.backend.routing.dto.GeoPoint;
import kr.ssafy.ieumgil.backend.routing.dto.GhPath;
import kr.ssafy.ieumgil.backend.routing.dto.GhRouteResponse;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchRequest;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchResponse;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class RouteSearchServiceTest {
    private static final GeoPoint ORIGIN = new GeoPoint(35.083322, 128.818527);
    private static final GeoPoint DESTINATION = new GeoPoint(35.130342, 128.943911);

    @Test
    void returnsSafeAndShortestWhenOptionIsOmitted() {
        RouteSearchService service = new RouteSearchService(new FakeGraphHopperClient(false), new RoutingProfileResolver());

        RouteSearchResponse response = service.search(new RouteSearchRequest(
                DisabilityType.VISUAL,
                null,
                ORIGIN,
                DESTINATION
        ));

        assertThat(response.routes()).hasSize(2);
        assertThat(response.routes()).extracting("routeOption").containsExactly(RouteOption.SAFE, RouteOption.SHORTEST);
        assertThat(response.routes()).extracting("graphhopperProfile").containsExactly("visual_safe", "visual_fast");
        assertThat(response.routes()).allMatch(route -> route.available());
    }

    @Test
    void returnsUnavailableInsteadOfSyntheticRouteWhenGraphHopperFails() {
        RouteSearchService service = new RouteSearchService(new FakeGraphHopperClient(true), new RoutingProfileResolver());

        RouteSearchResponse response = service.search(new RouteSearchRequest(
                DisabilityType.MOBILITY,
                RouteOption.SAFE,
                ORIGIN,
                DESTINATION
        ));

        assertThat(response.routes()).hasSize(1);
        assertThat(response.routes().getFirst().available()).isFalse();
        assertThat(response.routes().getFirst().reason()).isEqualTo("POINT_NOT_SNAPPABLE");
        assertThat(response.routes().getFirst().geometry()).isNull();
    }

    private static final class FakeGraphHopperClient implements GraphHopperRoutingClient {
        private final boolean fail;
        private final ObjectMapper objectMapper = new ObjectMapper();

        private FakeGraphHopperClient(boolean fail) {
            this.fail = fail;
        }

        @Override
        public GhRouteResponse route(GeoPoint origin, GeoPoint destination, String profile, List<String> details) {
            if (fail) {
                throw new GraphHopperRouteException("POINT_NOT_SNAPPABLE", "Cannot find point");
            }
            return new GhRouteResponse(List.of(new GhPath(
                    100.0,
                    120_000,
                    95.5,
                    false,
                    objectMapper.createObjectNode().put("type", "LineString"),
                    List.of(),
                    Map.of()
            )), null);
        }
    }
}
