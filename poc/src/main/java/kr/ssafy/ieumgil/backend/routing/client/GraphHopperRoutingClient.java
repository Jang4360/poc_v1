package kr.ssafy.ieumgil.backend.routing.client;

import kr.ssafy.ieumgil.backend.routing.dto.GeoPoint;
import kr.ssafy.ieumgil.backend.routing.dto.GhRouteResponse;

import java.util.List;

public interface GraphHopperRoutingClient {
    GhRouteResponse route(GeoPoint origin, GeoPoint destination, String profile, List<String> details);
}
