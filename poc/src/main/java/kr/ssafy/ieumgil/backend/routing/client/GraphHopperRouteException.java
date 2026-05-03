package kr.ssafy.ieumgil.backend.routing.client;

public class GraphHopperRouteException extends RuntimeException {
    private final String reason;

    public GraphHopperRouteException(String reason, String message) {
        super(message);
        this.reason = reason;
    }

    public String reason() {
        return reason;
    }
}
