package kr.ssafy.ieumgil.graphhopper;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.EdgeIntAccess;
import com.graphhopper.routing.ev.EnumEncodedValue;
import com.graphhopper.routing.util.parsers.TagParser;
import com.graphhopper.storage.IntsRef;

final class IeumEnumTagParser<E extends Enum<E>> implements TagParser {
    private final String osmTag;
    private final EnumEncodedValue<E> encodedValue;
    private final Class<E> enumClass;
    private final E fallback;

    IeumEnumTagParser(String osmTag, EnumEncodedValue<E> encodedValue, Class<E> enumClass, E fallback) {
        this.osmTag = osmTag;
        this.encodedValue = encodedValue;
        this.enumClass = enumClass;
        this.fallback = fallback;
    }

    @Override
    public void handleWayTags(int edgeId, EdgeIntAccess edgeIntAccess, ReaderWay way, IntsRef relationFlags) {
        encodedValue.setEnum(false, edgeId, edgeIntAccess, parseEnum(way.getTag(osmTag)));
    }

    private E parseEnum(Object rawValue) {
        if (rawValue == null) {
            return fallback;
        }
        String value = rawValue.toString().trim();
        if (value.isEmpty()) {
            return fallback;
        }
        try {
            return Enum.valueOf(enumClass, value);
        } catch (IllegalArgumentException ignored) {
            return fallback;
        }
    }
}
