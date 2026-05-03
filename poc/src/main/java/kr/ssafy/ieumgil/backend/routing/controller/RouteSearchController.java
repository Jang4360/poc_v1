package kr.ssafy.ieumgil.backend.routing.controller;

import jakarta.validation.Valid;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchRequest;
import kr.ssafy.ieumgil.backend.routing.dto.RouteSearchResponse;
import kr.ssafy.ieumgil.backend.routing.service.RouteSearchService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/routes")
public class RouteSearchController {
    private final RouteSearchService routeSearchService;

    public RouteSearchController(RouteSearchService routeSearchService) {
        this.routeSearchService = routeSearchService;
    }

    @PostMapping("/search")
    public RouteSearchResponse search(@Valid @RequestBody RouteSearchRequest request) {
        return routeSearchService.search(request);
    }
}
