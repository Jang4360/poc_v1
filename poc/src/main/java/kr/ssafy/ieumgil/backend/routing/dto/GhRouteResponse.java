package kr.ssafy.ieumgil.backend.routing.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record GhRouteResponse(List<GhPath> paths, String message) {
}
