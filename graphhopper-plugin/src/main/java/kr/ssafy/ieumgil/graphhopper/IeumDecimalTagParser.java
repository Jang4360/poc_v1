package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.DecimalEncodedValue;
import com.graphhopper.routing.ev.EdgeIntAccess;
import com.graphhopper.routing.util.parsers.TagParser;
import com.graphhopper.storage.IntsRef;

final class IeumDecimalTagParser implements TagParser {
    private final String osmTag;
    private final DecimalEncodedValue encodedValue;
    private final double fallback;

    IeumDecimalTagParser(String osmTag, DecimalEncodedValue encodedValue, double fallback) {
        this.osmTag = osmTag;
        this.encodedValue = encodedValue;
        this.fallback = fallback;
    }

    @Override
    public void handleWayTags(int edgeId, EdgeIntAccess edgeIntAccess, ReaderWay way, IntsRef relationFlags) {
        encodedValue.setDecimal(false, edgeId, edgeIntAccess, parseDecimal(way.getTag(osmTag)));
    }

    private double parseDecimal(Object rawValue) {
        if (rawValue == null) {
            return fallback;
        }
        String value = rawValue.toString().trim();
        if (value.isEmpty() || "UNKNOWN".equalsIgnoreCase(value)) {
            return fallback;
        }
        try {
            return Double.parseDouble(value);
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }
}
