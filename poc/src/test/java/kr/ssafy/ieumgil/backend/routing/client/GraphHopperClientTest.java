package kr.ssafy.ieumgil.backend.routing.client;

import kr.ssafy.ieumgil.backend.routing.dto.GeoPoint;
import kr.ssafy.ieumgil.backend.routing.dto.GhRouteResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.allOf;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.http.HttpMethod.GET;

class GraphHopperClientTest {
    @Test
    void callsGraphHopperRouteWithProfileAndPathDetails() {
        RestTemplate restTemplate = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();
        GraphHopperClient client = new GraphHopperClient(restTemplate, "http://graphhopper:8989");

        server.expect(requestTo(allOf(
                        containsString("profile=visual_safe"),
                        containsString("point=35.083322,128.818527"),
                        containsString("point=35.130342,128.943911"),
                        containsString("points_encoded=false"),
                        containsString("instructions=true"),
                        containsString("details=avg_slope_percent"),
                        containsString("details=width_state")
                )))
                .andExpect(method(GET))
                .andRespond(withSuccess("""
                        {
                          "paths": [{
                            "distance": 10.5,
                            "time": 1000,
                            "weight": 12.25,
                            "points_encoded": false,
                            "points": {"type": "LineString", "coordinates": [[128.0,35.0],[128.1,35.1]]},
                            "instructions": [],
                            "details": {"width_state": [{"first":0,"last":1,"length":1,"value":"ADEQUATE_150"}]}
                          }]
                        }
                        """, MediaType.APPLICATION_JSON));

        GhRouteResponse response = client.route(
                new GeoPoint(35.083322, 128.818527),
                new GeoPoint(35.130342, 128.943911),
                "visual_safe",
                List.of("avg_slope_percent", "width_state")
        );

        assertThat(response.paths()).hasSize(1);
        assertThat(response.paths().getFirst().distance()).isEqualTo(10.5);
        assertThat(response.paths().getFirst().points().get("type").asText()).isEqualTo("LineString");
        server.verify();
    }

    @Test
    void convertsGraphHopperBadRequestToRouteException() {
        RestTemplate restTemplate = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();
        GraphHopperClient client = new GraphHopperClient(restTemplate, "http://graphhopper:8989");

        server.expect(requestTo(containsString("/route")))
                .andRespond(withBadRequest().body("{\"message\":\"Cannot find point 0\"}").contentType(MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.route(
                new GeoPoint(0.0, 0.0),
                new GeoPoint(1.0, 1.0),
                "visual_safe",
                List.of()
        ))
                .isInstanceOf(GraphHopperRouteException.class)
                .extracting("reason")
                .isEqualTo("POINT_NOT_SNAPPABLE");

        server.verify();
    }
}
