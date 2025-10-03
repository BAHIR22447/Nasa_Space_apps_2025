import os
import ee
from flask import jsonify
import functions_framework

def ee_init():
    SERVICE_ACCOUNT = os.environ.get("EE_SERVICE_ACCOUNT")
    PRIVATE_KEY_JSON = os.environ.get("EE_PRIVATE_KEY")
    credentials = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, key_data=PRIVATE_KEY_JSON)
    ee.Initialize(credentials)

@functions_framework.http
def openaq(request):
    try:
        ee_init()

        # Load asset
        all_points = ee.FeatureCollection("projects/saasbusiness-49fbe/assets/openaq_measurements")

        # Extract lon, lat, value
        def prep_points(f):
            lon = ee.Number(f.get("lon"))
            lat = ee.Number(f.get("lat"))
            value = ee.Number(f.get("value"))
            return ee.Feature(ee.Geometry.Point([lon, lat]), {"value": value})
        
        # Separate PM2.5 and NO2
        pm25_points = all_points.filterMetadata("parameter", "equals", "pm25").map(prep_points)
        no2_points = all_points.filterMetadata("parameter", "equals", "no2").map(prep_points)

        # Region: North America
        na = ee.Geometry.Rectangle([-170, 5, -50, 85])

        # Interpolation
        scale = 5000
        max_dist = 200e3
        kernel = ee.Kernel.gaussian(
            radius=100e3,
            sigma=50e3,
            units="meters"
        )

        def interpolate(points):
            idw = points.reduceToImage(
                properties=["value"], reducer=ee.Reducer.first()
            )
            interp = idw.focal_mean(kernel=kernel).reproject(
                "EPSG:4326", None, scale
            ).clip(na)
            mask = points.distance().lte(max_dist)
            return interp.updateMask(mask)

        pm25_img = interpolate(pm25_points)
        no2_img = interpolate(no2_points)

        palette = [
            "000080","0000D9","4000FF","8000FF","0080FF",
            "00D9FF","80FFFF","FF8080","D90000","800000"
        ]

        pm25_vis = {"min": 0, "max": 50, "palette": palette}
        no2_vis = {"min": 0, "max": 50, "palette": palette}

        pm25_map = pm25_img.getMapId(pm25_vis)
        no2_map = no2_img.getMapId(no2_vis)

        return jsonify({
            "pm25": {
                "map_id": pm25_map["mapid"],
                "url_template": f"/tile/{pm25_map['mapid']}/{{z}}/{{x}}/{{y}}"
            },
            "no2": {
                "map_id": no2_map["mapid"],
                "url_template": f"/tile/{no2_map['mapid']}/{{z}}/{{x}}/{{y}}"
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
