package kr.ssafy.ieumgil.backend.routing.client;

import kr.ssafy.ieumgil.backend.routing.dto.GeoPoint;
import kr.ssafy.ieumgil.backend.routing.dto.GhRouteResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.List;

@Component
public class GraphHopperClient implements GraphHopperRoutingClient {
    public static final List<String> WALK_DETAILS = List.of(
            "walk_access",
            "avg_slope_percent",
            "width_meter",
            "braille_block_state",
            "audio_signal_state",
            "slope_state",
            "width_state",
            "surface_state",
            "stairs_state",
            "signal_state",
            "segment_type"
    );

    private final RestTemplate restTemplate;
    private final String baseUrl;

    @Autowired
    public GraphHopperClient(
            RestTemplateBuilder restTemplateBuilder,
            @Value("${ieumgil.graphhopper.base-url}") String baseUrl
    ) {
        this(restTemplateBuilder.build(), baseUrl);
    }

    GraphHopperClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = trimTrailingSlash(baseUrl);
    }

    @Override
    public GhRouteResponse route(GeoPoint origin, GeoPoint destination, String profile, List<String> details) {
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(baseUrl + "/route")
                .queryParam("point", formatPoint(origin))
                .queryParam("point", formatPoint(destination))
                .queryParam("profile", profile)
                .queryParam("points_encoded", "false")
                .queryParam("instructions", "true");
        details.forEach(detail -> builder.queryParam("details", detail));

        URI uri = builder.build(true).toUri();
        try {
            return restTemplate.getForObject(uri, GhRouteResponse.class);
        } catch (RestClientResponseException e) {
            throw new GraphHopperRouteException(resolveReason(e), e.getResponseBodyAsString());
        } catch (RuntimeException e) {
            throw new GraphHopperRouteException("GRAPHHOPPER_UNAVAILABLE", e.getMessage());
        }
    }

    private static String formatPoint(GeoPoint point) {
        return point.lat() + "," + point.lon();
    }

    private static String trimTrailingSlash(String value) {
        if (value == null || value.isBlank()) {
            return "http://localhost:8989";
        }
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private static String resolveReason(RestClientResponseException e) {
        String body = e.getResponseBodyAsString();
        if (body.contains("Cannot find point") || body.contains("Cannot find closest point")) {
            return "POINT_NOT_SNAPPABLE";
        }
        if (e.getStatusCode().is4xxClientError()) {
            return "NO_ACCESSIBLE_ROUTE";
        }
        return "GRAPHHOPPER_UNAVAILABLE";
    }
}
