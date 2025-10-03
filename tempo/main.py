import os
import ee
from flask import jsonify, Response
import functions_framework

def ee_init():
    SERVICE_ACCOUNT = os.environ.get("EE_SERVICE_ACCOUNT")
    PRIVATE_KEY_JSON = os.environ.get("EE_PRIVATE_KEY")
    credentials = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, key_data=PRIVATE_KEY_JSON)
    ee.Initialize(credentials)

def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@functions_framework.http
def tempo(request):
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return add_cors_headers(Response("", status=204))

    try:
        ee_init()
        collection = ee.ImageCollection("NASA/TEMPO/NO2_L3").sort("system:time_start", False)
        image = collection.first()
        if not image:
            return add_cors_headers(jsonify({"error": "No TEMPO images found"})), 404

        vis_params = {
            "min": 0,
            "max": 1.5e16,
            "bands": ["vertical_column_troposphere"],
            "palette": [
                '000080','0000D9','4000FF','8000FF','0080FF',
                '00D9FF','80FFFF','FF8080','D90000','800000'
            ]
        }
        map_dict = image.getMapId(vis_params)

        response = jsonify({
            "map_id": map_dict["mapid"],
            "url_template": f"/tile/{map_dict['mapid']}/{{z}}/{{x}}/{{y}}"
        })
        return add_cors_headers(response)
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500
