package kr.ssafy.ieumgil.graphhopper;

import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.util.StdDateFormat;
import com.fasterxml.jackson.datatype.jdk8.Jdk8Module;
import com.graphhopper.GraphHopper;
import com.graphhopper.GraphHopperConfig;
import com.graphhopper.application.GraphHopperServerConfiguration;
import com.graphhopper.application.resources.RootResource;
import com.graphhopper.http.CORSFilter;
import com.graphhopper.http.GHRequestTransformer;
import com.graphhopper.http.ProfileResolver;
import com.graphhopper.jackson.Jackson;
import com.graphhopper.http.health.GraphHopperHealthCheck;
import com.graphhopper.navigation.NavigateResource;
import com.graphhopper.resources.HealthCheckResource;
import com.graphhopper.resources.I18NResource;
import com.graphhopper.resources.InfoResource;
import com.graphhopper.resources.RouteResource;
import io.dropwizard.Application;
import io.dropwizard.assets.AssetsBundle;
import io.dropwizard.setup.Bootstrap;
import io.dropwizard.setup.Environment;

import javax.servlet.DispatcherType;
import java.util.EnumSet;

public final class IeumGraphHopperApplication extends Application<GraphHopperServerConfiguration> {
    public static void main(String[] args) throws Exception {
        new IeumGraphHopperApplication().run(args);
    }

    @Override
    public void initialize(Bootstrap<GraphHopperServerConfiguration> bootstrap) {
        bootstrap.getObjectMapper().registerModule(new Jdk8Module());
        Jackson.initObjectMapper(bootstrap.getObjectMapper());
        bootstrap.getObjectMapper().setDateFormat(new StdDateFormat());
        bootstrap.getObjectMapper().enable(MapperFeature.ALLOW_EXPLICIT_PROPERTY_RENAMING);
        bootstrap.addBundle(new AssetsBundle("/com/graphhopper/maps/", "/maps/", "index.html"));
        bootstrap.addBundle(new AssetsBundle("/META-INF/resources/webjars", "/webjars/", null, "webjars"));
    }

    @Override
    public void run(GraphHopperServerConfiguration configuration, Environment environment) {
        GraphHopperConfig graphHopperConfig = configuration.getGraphHopperConfiguration();
        IeumGraphHopperManaged managed = new IeumGraphHopperManaged(graphHopperConfig);
        managed.start();
        environment.lifecycle().manage(managed);

        GraphHopper graphHopper = managed.getGraphHopper();
        ProfileResolver profileResolver = new ProfileResolver(graphHopperConfig.getProfiles());
        GHRequestTransformer requestTransformer = request -> request;

        environment.jersey().register(new RootResource());
        environment.jersey().register(new RouteResource(graphHopperConfig, graphHopper, profileResolver, requestTransformer, false));
        environment.jersey().register(new InfoResource(graphHopperConfig, graphHopper, false));
        environment.jersey().register(new I18NResource(graphHopper.getTranslationMap()));
        environment.jersey().register(new NavigateResource(graphHopper, graphHopper.getTranslationMap(), graphHopperConfig));
        environment.healthChecks().register("graphhopper", new GraphHopperHealthCheck(graphHopper));
        environment.jersey().register(new HealthCheckResource(environment.healthChecks()));

        environment.servlets()
                .addFilter("cors", CORSFilter.class)
                .addMappingForUrlPatterns(EnumSet.allOf(DispatcherType.class), false, "*");
    }
}
