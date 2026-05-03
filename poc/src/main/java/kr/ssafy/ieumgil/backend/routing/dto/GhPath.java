package kr.ssafy.ieumgil.backend.routing.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public record GhPath(
        double distance,
        long time,
        double weight,
        boolean points_encoded,
        JsonNode points,
        List<GhInstruction> instructions,
        Map<String, JsonNode> details
) {
}
