import os
import ee
import requests
import json
from flask import Response
import functions_framework

def ee_init():
    SERVICE_ACCOUNT = os.environ.get("EE_SERVICE_ACCOUNT")
    PRIVATE_KEY_JSON = os.environ.get("EE_PRIVATE_KEY")
    credentials = ee.ServiceAccountCredentials(
        SERVICE_ACCOUNT,
        key_data=PRIVATE_KEY_JSON
    )
    ee.Initialize(credentials)

def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@functions_framework.http
def tile(request):
    """
    Proxy tiles from EE to client.
    URL pattern: /tile/projects/earthengine-legacy/maps/<mapid>/<z>/<x>/<y>
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return add_cors_headers(Response("", status=204))

    try:
        ee_init()

        parts = request.path.strip("/").split("/")
        # Example: ['tile', 'projects', 'earthengine-legacy', 'maps', '<mapid>', 'z', 'x', 'y']

        if "maps" not in parts:
            return add_cors_headers(Response("Invalid tile URL: missing 'maps'", status=400))

        maps_index = parts.index("maps")
        if len(parts) < maps_index + 4:
            return add_cors_headers(Response("Invalid tile URL: not enough parts", status=400))

        # Build mapid path: projects/earthengine-legacy/maps/<mapid>
        mapid = "/".join(parts[maps_index-2:maps_index+1]) + "/" + parts[maps_index+1]

        # Extract z/x/y
        z, x, y = map(int, parts[maps_index+2:maps_index+5])

        # Manually build tile URL with new EE API
        tile_url = f"https://earthengine.googleapis.com/v1/{mapid}/tiles/{z}/{x}/{y}"

        # Get fresh access token for service account
        import google.auth.transport.requests
        from google.oauth2 import service_account

        PRIVATE_KEY_JSON = os.environ.get("EE_PRIVATE_KEY")
        key_dict = json.loads(PRIVATE_KEY_JSON)

        creds = service_account.Credentials.from_service_account_info(
            key_dict,
            scopes=["https://www.googleapis.com/auth/earthengine"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        headers = {"Authorization": f"Bearer {creds.token}"}

        # Fetch tile
        r = requests.get(tile_url, headers=headers, timeout=30)
        r.raise_for_status()

        response = Response(r.content, mimetype="image/png")
        return add_cors_headers(response)

    except Exception as e:
        return add_cors_headers(Response(f"Tile proxy error: {e}", status=500))
