package kr.ssafy.ieumgil.backend.routing.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record GhInstruction(
        double distance,
        long time,
        String text,
        int sign,
        List<Integer> interval,
        String street_name
) {
}
