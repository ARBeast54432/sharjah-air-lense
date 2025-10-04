# gee_onefile_test.py
import ee, os, sys, traceback

print("Home folder:", os.path.expanduser("~"))
print("Running Python:", sys.executable)

try:
    print("\nCalling ee.Authenticate() — follow browser steps if a link opens...")
    ee.Authenticate()  # opens browser link to authenticate your Google account
except Exception:
    print("ee.Authenticate() raised an exception (may be fine if already authenticated).")

try:
    print("\nCalling ee.Initialize() ...")
    ee.Initialize()
    print("✅ ee.Initialize succeeded.")
except Exception:
    print("\n❌ ee.Initialize failed. Full traceback below:")
    traceback.print_exc()
    print("\nQuick checks:")
    print("1) Did you sign up for Earth Engine? (https://earthengine.google.com/signup)")
    print("2) Make sure you authenticated with the SAME Google account used to sign up.")
    sys.exit(1)

# quick test if Initialize succeeded
try:
    sharjah = ee.Geometry.Rectangle([55.8, 25.0, 56.6, 25.6])
    coll = ee.ImageCollection('MODIS/061/MCD19A2_GRANULES') \
        .select('Optical_Depth_047') \
        .filterBounds(sharjah).filterDate('2025-10-01','2025-10-03')
    img = coll.mean()
    mean = img.reduceRegion(ee.Reducer.mean(), sharjah, scale=1000)
    print("\nMean AOD result from Earth Engine:", mean.getInfo())
except Exception:
    print("\nError during test (collection name or date range may be unavailable).")
    traceback.print_exc()
