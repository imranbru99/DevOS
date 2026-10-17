#!/usr/bin/env python3
"""
DevOS Islamic - prayer times, Hijri date and Qibla, in pure Python stdlib.

Nothing here touches the network or a display, so the same code runs in the
app, in the background notifier and in the unit tests on any machine.

The sun-position maths follows the well-known "PrayTimes" approach (low
precision solar coordinates, good to well under a minute for the years we
care about), which is also what most published timetables use. The times are
rounded to the nearest minute like printed mosque timetables.

Methods (Fajr angle / Isha angle or interval):
  karachi   University of Islamic Sciences, Karachi   18 / 18   (default -
            this is what the Islamic Foundation Bangladesh and most of South
            Asia use)
  mwl       Muslim World League                       18 / 17
  isna      Islamic Society of North America          15 / 15
  egypt     Egyptian General Authority of Survey      19.5 / 17.5
  makkah    Umm al-Qura University, Makkah            18.5 / 90 min after Maghrib

Asr: "hanafi" (shadow = 2x object length + noon shadow, default for South
Asia) or "shafi" (1x; also what Maliki and Hanbali use).

High latitudes: when the sun never gets low enough for the Fajr/Isha angle
(e.g. London in June) we use the "angle based" rule - Fajr is at most
angle/60 of the night before sunrise, Isha at most angle/60 after sunset.
"""

import datetime as _dt
import math

KAABA = (21.4225, 39.8262)

METHODS = {
    "karachi": {"name": "University of Islamic Sciences, Karachi", "fajr": 18.0, "isha": 18.0},
    "mwl": {"name": "Muslim World League", "fajr": 18.0, "isha": 17.0},
    "isna": {"name": "Islamic Society of North America (ISNA)", "fajr": 15.0, "isha": 15.0},
    "egypt": {"name": "Egyptian General Authority of Survey", "fajr": 19.5, "isha": 17.5},
    "makkah": {"name": "Umm al-Qura University, Makkah", "fajr": 18.5, "isha_minutes": 90},
}
DEFAULT_METHOD = "karachi"
ASR_FACTORS = {"hanafi": 2, "shafi": 1}
DEFAULT_ASR = "hanafi"

PRAYERS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
PRAYER_LABELS = {
    "fajr": "Fajr", "sunrise": "Sunrise", "dhuhr": "Dhuhr",
    "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha",
}
# Sunrise is shown for planning (Fajr ends) but it is not a prayer, so the
# notifier and the "next prayer" highlight skip it.
SALAH = ("fajr", "dhuhr", "asr", "maghrib", "isha")

# The sun's upper edge touches the horizon at 0.833 deg below it (refraction
# plus the sun's radius).
SUNRISE_ANGLE = 0.833


# ---------------------------------------------------------------------------
# Cities
# ---------------------------------------------------------------------------
# name: (latitude, longitude, IANA time zone, standard UTC offset in hours).
# The fixed offset is only a fallback for machines without tz data (e.g. a
# bare Windows Python); on DevOS zoneinfo is always used, so DST is correct.

CITIES = {
    # Bangladesh - the 8 division cities
    "Dhaka": (23.8103, 90.4125, "Asia/Dhaka", 6),
    "Chattogram": (22.3569, 91.7832, "Asia/Dhaka", 6),
    "Rajshahi": (24.3745, 88.6042, "Asia/Dhaka", 6),
    "Khulna": (22.8456, 89.5403, "Asia/Dhaka", 6),
    "Barishal": (22.7010, 90.3535, "Asia/Dhaka", 6),
    "Sylhet": (24.8949, 91.8687, "Asia/Dhaka", 6),
    "Rangpur": (25.7439, 89.2752, "Asia/Dhaka", 6),
    "Mymensingh": (24.7471, 90.4203, "Asia/Dhaka", 6),
    # Bangladesh - district towns
    "Gazipur": (23.9999, 90.4203, "Asia/Dhaka", 6),
    "Narayanganj": (23.6238, 90.5000, "Asia/Dhaka", 6),
    "Narsingdi": (23.9322, 90.7151, "Asia/Dhaka", 6),
    "Munshiganj": (23.5422, 90.5305, "Asia/Dhaka", 6),
    "Manikganj": (23.8617, 90.0003, "Asia/Dhaka", 6),
    "Tangail": (24.2513, 89.9167, "Asia/Dhaka", 6),
    "Kishoreganj": (24.4449, 90.7766, "Asia/Dhaka", 6),
    "Faridpur": (23.6071, 89.8429, "Asia/Dhaka", 6),
    "Madaripur": (23.1641, 90.1896, "Asia/Dhaka", 6),
    "Gopalganj": (23.0050, 89.8266, "Asia/Dhaka", 6),
    "Shariatpur": (23.2423, 90.4348, "Asia/Dhaka", 6),
    "Rajbari": (23.7574, 89.6445, "Asia/Dhaka", 6),
    "Cumilla": (23.4607, 91.1809, "Asia/Dhaka", 6),
    "Brahmanbaria": (23.9571, 91.1119, "Asia/Dhaka", 6),
    "Chandpur": (23.2333, 90.6713, "Asia/Dhaka", 6),
    "Feni": (23.0159, 91.3976, "Asia/Dhaka", 6),
    "Noakhali": (22.8696, 91.0995, "Asia/Dhaka", 6),
    "Lakshmipur": (22.9447, 90.8282, "Asia/Dhaka", 6),
    "Cox's Bazar": (21.4272, 92.0058, "Asia/Dhaka", 6),
    "Rangamati": (22.6533, 92.1789, "Asia/Dhaka", 6),
    "Bandarban": (22.1953, 92.2184, "Asia/Dhaka", 6),
    "Khagrachhari": (23.1193, 91.9847, "Asia/Dhaka", 6),
    "Bogura": (24.8465, 89.3773, "Asia/Dhaka", 6),
    "Pabna": (24.0064, 89.2372, "Asia/Dhaka", 6),
    "Sirajganj": (24.4534, 89.7007, "Asia/Dhaka", 6),
    "Natore": (24.4206, 89.0003, "Asia/Dhaka", 6),
    "Naogaon": (24.8104, 88.9409, "Asia/Dhaka", 6),
    "Chapainawabganj": (24.5965, 88.2775, "Asia/Dhaka", 6),
    "Joypurhat": (25.0968, 89.0227, "Asia/Dhaka", 6),
    "Jashore": (23.1664, 89.2081, "Asia/Dhaka", 6),
    "Kushtia": (23.9013, 89.1204, "Asia/Dhaka", 6),
    "Jhenaidah": (23.5450, 89.1726, "Asia/Dhaka", 6),
    "Magura": (23.4873, 89.4199, "Asia/Dhaka", 6),
    "Narail": (23.1725, 89.5127, "Asia/Dhaka", 6),
    "Chuadanga": (23.6402, 88.8418, "Asia/Dhaka", 6),
    "Meherpur": (23.7622, 88.6318, "Asia/Dhaka", 6),
    "Satkhira": (22.7185, 89.0705, "Asia/Dhaka", 6),
    "Bagerhat": (22.6516, 89.7859, "Asia/Dhaka", 6),
    "Bhola": (22.6859, 90.6482, "Asia/Dhaka", 6),
    "Patuakhali": (22.3596, 90.3299, "Asia/Dhaka", 6),
    "Pirojpur": (22.5841, 89.9720, "Asia/Dhaka", 6),
    "Jhalokati": (22.6406, 90.1987, "Asia/Dhaka", 6),
    "Barguna": (22.1591, 90.1119, "Asia/Dhaka", 6),
    "Habiganj": (24.3745, 91.4155, "Asia/Dhaka", 6),
    "Moulvibazar": (24.4829, 91.7774, "Asia/Dhaka", 6),
    "Sunamganj": (25.0658, 91.3950, "Asia/Dhaka", 6),
    "Dinajpur": (25.6217, 88.6354, "Asia/Dhaka", 6),
    "Thakurgaon": (26.0336, 88.4616, "Asia/Dhaka", 6),
    "Panchagarh": (26.3411, 88.5542, "Asia/Dhaka", 6),
    "Nilphamari": (25.9310, 88.8560, "Asia/Dhaka", 6),
    "Lalmonirhat": (25.9923, 89.2847, "Asia/Dhaka", 6),
    "Kurigram": (25.8072, 89.6295, "Asia/Dhaka", 6),
    "Gaibandha": (25.3288, 89.5280, "Asia/Dhaka", 6),
    "Jamalpur": (24.9375, 89.9378, "Asia/Dhaka", 6),
    "Sherpur": (25.0205, 90.0153, "Asia/Dhaka", 6),
    "Netrokona": (24.8835, 90.7279, "Asia/Dhaka", 6),
    # Middle East
    "Makkah": (21.4225, 39.8262, "Asia/Riyadh", 3),
    "Madinah": (24.4672, 39.6111, "Asia/Riyadh", 3),
    "Riyadh": (24.7136, 46.6753, "Asia/Riyadh", 3),
    "Jeddah": (21.4858, 39.1925, "Asia/Riyadh", 3),
    "Dubai": (25.2048, 55.2708, "Asia/Dubai", 4),
    "Abu Dhabi": (24.4539, 54.3773, "Asia/Dubai", 4),
    "Doha": (25.2854, 51.5310, "Asia/Qatar", 3),
    "Kuwait City": (29.3759, 47.9774, "Asia/Kuwait", 3),
    "Manama": (26.2285, 50.5860, "Asia/Bahrain", 3),
    "Muscat": (23.5880, 58.3829, "Asia/Muscat", 4),
    "Baghdad": (33.3152, 44.3661, "Asia/Baghdad", 3),
    "Tehran": (35.6892, 51.3890, "Asia/Tehran", 3.5),
    "Amman": (31.9454, 35.9284, "Asia/Amman", 3),
    "Jerusalem": (31.7683, 35.2137, "Asia/Jerusalem", 2),
    "Beirut": (33.8938, 35.5018, "Asia/Beirut", 2),
    "Istanbul": (41.0082, 28.9784, "Europe/Istanbul", 3),
    "Ankara": (39.9334, 32.8597, "Europe/Istanbul", 3),
    # South and Central Asia
    "Karachi": (24.8607, 67.0011, "Asia/Karachi", 5),
    "Lahore": (31.5204, 74.3587, "Asia/Karachi", 5),
    "Islamabad": (33.6844, 73.0479, "Asia/Karachi", 5),
    "Delhi": (28.6139, 77.2090, "Asia/Kolkata", 5.5),
    "Mumbai": (19.0760, 72.8777, "Asia/Kolkata", 5.5),
    "Kolkata": (22.5726, 88.3639, "Asia/Kolkata", 5.5),
    "Hyderabad": (17.3850, 78.4867, "Asia/Kolkata", 5.5),
    "Kathmandu": (27.7172, 85.3240, "Asia/Kathmandu", 5.75),
    "Colombo": (6.9271, 79.8612, "Asia/Colombo", 5.5),
    "Kabul": (34.5553, 69.2075, "Asia/Kabul", 4.5),
    "Tashkent": (41.2995, 69.2401, "Asia/Tashkent", 5),
    # East and South-East Asia, Oceania
    "Kuala Lumpur": (3.1390, 101.6869, "Asia/Kuala_Lumpur", 8),
    "Singapore": (1.3521, 103.8198, "Asia/Singapore", 8),
    "Jakarta": (-6.2088, 106.8456, "Asia/Jakarta", 7),
    "Beijing": (39.9042, 116.4074, "Asia/Shanghai", 8),
    "Tokyo": (35.6762, 139.6503, "Asia/Tokyo", 9),
    "Sydney": (-33.8688, 151.2093, "Australia/Sydney", 10),
    "Melbourne": (-37.8136, 144.9631, "Australia/Melbourne", 10),
    # Africa
    "Cairo": (30.0444, 31.2357, "Africa/Cairo", 2),
    "Casablanca": (33.5731, -7.5898, "Africa/Casablanca", 1),
    "Lagos": (6.5244, 3.3792, "Africa/Lagos", 1),
    "Nairobi": (-1.2921, 36.8219, "Africa/Nairobi", 3),
    "Johannesburg": (-26.2041, 28.0473, "Africa/Johannesburg", 2),
    # Europe
    "London": (51.5074, -0.1278, "Europe/London", 0),
    "Birmingham": (52.4862, -1.8904, "Europe/London", 0),
    "Paris": (48.8566, 2.3522, "Europe/Paris", 1),
    "Berlin": (52.5200, 13.4050, "Europe/Berlin", 1),
    "Stockholm": (59.3293, 18.0686, "Europe/Stockholm", 1),
    # Americas
    "New York": (40.7128, -74.0060, "America/New_York", -5),
    "Chicago": (41.8781, -87.6298, "America/Chicago", -6),
    "Los Angeles": (34.0522, -118.2437, "America/Los_Angeles", -8),
    "Toronto": (43.6532, -79.3832, "America/Toronto", -5),
}

# Accept the older/English spellings people still type.
CITY_ALIASES = {
    "chittagong": "Chattogram", "barisal": "Barishal", "comilla": "Cumilla",
    "bogra": "Bogura", "jessore": "Jashore", "mecca": "Makkah", "medina": "Madinah",
    "coxs bazar": "Cox's Bazar", "cox bazar": "Cox's Bazar", "nawabganj": "Chapainawabganj",
    "new delhi": "Delhi", "bombay": "Mumbai", "calcutta": "Kolkata", "kl": "Kuala Lumpur",
}


def _norm(text):
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()


def find_city(name):
    """Exact (case/punctuation-insensitive) lookup; returns (name, data) or None."""
    key = _norm(name or "")
    for city in CITIES:
        if _norm(city) == key:
            return city, CITIES[city]
    alias = CITY_ALIASES.get(key)
    if alias:
        return alias, CITIES[alias]
    return None


def search_cities(query, limit=20):
    """Cities whose name (or alias) starts with / contains the query; prefix hits first."""
    key = _norm(query or "")
    if not key:
        return sorted(CITIES)[:limit]
    prefix, inside = [], []
    names = list(CITIES) + [a for a in CITY_ALIASES]
    for name in names:
        real = CITY_ALIASES.get(name, name)
        n = _norm(name)
        if n.startswith(key):
            target = prefix
        elif key in n:
            target = inside
        else:
            continue
        if real not in prefix and real not in inside:
            target.append(real)
    return (prefix + inside)[:limit]


# ---------------------------------------------------------------------------
# Time zones
# ---------------------------------------------------------------------------

def get_tz(tz_name=None, fallback_hours=None):
    """A tzinfo for tz_name; falls back to a fixed offset if tz data is missing."""
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:  # no tzdata (bare Windows Python) or unknown name
            pass
    if fallback_hours is None:
        fallback_hours = 0
    return _dt.timezone(_dt.timedelta(hours=float(fallback_hours)))


def utc_offset_hours(tz, date):
    """UTC offset (hours) in effect at local noon on that date - handles DST days."""
    noon = _dt.datetime(date.year, date.month, date.day, 12, 0, tzinfo=tz)
    return noon.utcoffset().total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Degree-based trig helpers
# ---------------------------------------------------------------------------

def _dsin(d):
    return math.sin(math.radians(d))


def _dcos(d):
    return math.cos(math.radians(d))


def _dtan(d):
    return math.tan(math.radians(d))


def _darcsin(x):
    return math.degrees(math.asin(x))


def _darccos(x):
    return math.degrees(math.acos(x))


def _darctan2(y, x):
    return math.degrees(math.atan2(y, x))


def _darccot(x):
    return math.degrees(math.atan(1.0 / x))


def _fix(a, b):
    a = a - b * math.floor(a / b)
    return a + b if a < 0 else a


# ---------------------------------------------------------------------------
# Sun position and prayer times
# ---------------------------------------------------------------------------

def julian_day(year, month, day):
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def sun_position(jd):
    """(declination in degrees, equation of time in hours) for a Julian day."""
    d = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * d, 360)
    q = _fix(280.459 + 0.98564736 * d, 360)
    lon = _fix(q + 1.915 * _dsin(g) + 0.020 * _dsin(2 * g), 360)
    e = 23.439 - 0.00000036 * d
    ra = _darctan2(_dcos(e) * _dsin(lon), _dcos(lon)) / 15.0
    eqt = q / 15.0 - _fix(ra, 24)
    decl = _darcsin(_dsin(e) * _dsin(lon))
    return decl, eqt


class _Calc:
    """One day's calculation for one place (times in local-mean hours)."""

    def __init__(self, date, lat, lon):
        self.lat = lat
        self.lon = lon
        # Start from local noon so the sun position is sampled near the event.
        self.jd = julian_day(date.year, date.month, date.day) - lon / (15.0 * 24.0)

    def mid_day(self, t):
        _, eqt = sun_position(self.jd + t)
        return _fix(12 - eqt, 24)

    def sun_angle_time(self, angle, t, ccw=False):
        decl, _ = sun_position(self.jd + t)
        noon = self.mid_day(t)
        cos_h = (-_dsin(angle) - _dsin(decl) * _dsin(self.lat)) / (_dcos(decl) * _dcos(self.lat))
        if cos_h < -1 or cos_h > 1:
            return float("nan")  # the sun never reaches that angle today
        h = _darccos(cos_h) / 15.0
        return noon - h if ccw else noon + h

    def asr_time(self, factor, t):
        decl, _ = sun_position(self.jd + t)
        angle = -_darccot(factor + _dtan(abs(self.lat - decl)))
        return self.sun_angle_time(angle, t)


_FIRST_GUESS = {"fajr": 5, "sunrise": 6, "dhuhr": 12, "asr": 13, "sunset": 18, "isha": 18}


def compute_hours(date, lat, lon, offset_hours, method=DEFAULT_METHOD, asr=DEFAULT_ASR):
    """Prayer times as decimal local hours (may exceed 24 / be negative near poles)."""
    params = METHODS.get(method, METHODS[DEFAULT_METHOD])
    factor = ASR_FACTORS.get(asr, ASR_FACTORS[DEFAULT_ASR])
    c = _Calc(date, lat, lon)

    def one_pass(guess):
        p = {k: v / 24.0 for k, v in guess.items()}
        return {
            "fajr": c.sun_angle_time(params["fajr"], p["fajr"], ccw=True),
            "sunrise": c.sun_angle_time(SUNRISE_ANGLE, p["sunrise"], ccw=True),
            "dhuhr": c.mid_day(p["dhuhr"]),
            "asr": c.asr_time(factor, p["asr"]),
            "sunset": c.sun_angle_time(SUNRISE_ANGLE, p["sunset"]),
            "isha": c.sun_angle_time(params.get("isha", 18.0), p["isha"]),
        }

    # Two passes: first from rough day portions, then refine each event with
    # the sun position at (roughly) its own time. An event that does not
    # happen (NaN) keeps its rough guess for the second pass.
    t = one_pass(_FIRST_GUESS)
    t = one_pass({k: (_FIRST_GUESS[k] if math.isnan(v) else v) for k, v in t.items()})

    shift = offset_hours - lon / 15.0
    t = {k: v + shift for k, v in t.items()}
    if math.isnan(t["sunrise"]) or math.isnan(t["sunset"]):
        # Polar day/night: no sunrise to anchor to; assume a 12-hour day around Dhuhr.
        t["sunrise"] = t["dhuhr"] - 6
        t["sunset"] = t["dhuhr"] + 6
    if math.isnan(t["asr"]) or t["asr"] >= t["sunset"]:
        t["asr"] = (t["dhuhr"] + t["sunset"]) / 2
    t["maghrib"] = t["sunset"]
    if "isha_minutes" in params:
        t["isha"] = t["maghrib"] + params["isha_minutes"] / 60.0
    _adjust_high_latitude(t, params)
    return t


def _adjust_high_latitude(t, params):
    """Angle-based rule: Fajr/Isha never further than angle/60 of the night."""
    night = _fix(t["sunrise"] - t["sunset"], 24)
    fajr_portion = params["fajr"] / 60.0 * night
    if math.isnan(t["fajr"]) or _fix(t["sunrise"] - t["fajr"], 24) > fajr_portion:
        t["fajr"] = t["sunrise"] - fajr_portion
    if "isha_minutes" not in params:
        isha_portion = params["isha"] / 60.0 * night
        if math.isnan(t["isha"]) or _fix(t["isha"] - t["sunset"], 24) > isha_portion:
            t["isha"] = t["sunset"] + isha_portion


def prayer_times(date, lat, lon, tz=None, method=DEFAULT_METHOD, asr=DEFAULT_ASR, offset_hours=None):
    """
    Prayer times for a date as timezone-aware datetimes, rounded to the minute.

    tz: a tzinfo (from get_tz). offset_hours overrides it with a fixed offset
    (handy for "manual" locations). Returns an ordered dict PRAYERS -> datetime.
    """
    if tz is None:
        tz = _dt.timezone(_dt.timedelta(hours=float(offset_hours or 0)))
    if offset_hours is None:
        offset_hours = utc_offset_hours(tz, date)
    hours = compute_hours(date, lat, lon, offset_hours, method, asr)
    # Build in UTC and convert, so a DST change on this date cannot shift us.
    midnight_utc = _dt.datetime(date.year, date.month, date.day, tzinfo=_dt.timezone.utc)
    out = {}
    for name in PRAYERS:
        minutes = int(math.floor(hours[name] * 60 + 0.5))
        when_utc = midnight_utc + _dt.timedelta(minutes=minutes) - _dt.timedelta(hours=offset_hours)
        out[name] = when_utc.astimezone(tz)
    return out


def times_for_settings(date, settings):
    """prayer_times() using an islamic.json-style settings dict."""
    loc = resolve_location(settings)
    return prayer_times(date, loc["lat"], loc["lon"], loc["tz"],
                        settings.get("method", DEFAULT_METHOD), settings.get("asr", DEFAULT_ASR))


def resolve_location(settings):
    """{'name', 'lat', 'lon', 'tz'} from settings (a city name, or manual lat/lon/tz)."""
    if settings.get("manual"):
        m = settings["manual"]
        tz = get_tz(m.get("tz"), m.get("offset", 0))
        return {"name": m.get("name") or "%.4f, %.4f" % (m["lat"], m["lon"]),
                "lat": float(m["lat"]), "lon": float(m["lon"]), "tz": tz}
    found = find_city(settings.get("city", "Dhaka")) or find_city("Dhaka")
    name, (lat, lon, tz_name, std) = found
    return {"name": name, "lat": lat, "lon": lon, "tz": get_tz(tz_name, std)}


def next_prayer(times, now):
    """(name, datetime) of the next of the five daily prayers after `now`, or None."""
    for name in SALAH:
        if times[name] > now:
            return name, times[name]
    return None


# ---------------------------------------------------------------------------
# Qibla
# ---------------------------------------------------------------------------

def qibla(lat, lon):
    """Initial great-circle bearing (degrees from true north, clockwise) to the Kaaba."""
    lat1, lat2 = math.radians(lat), math.radians(KAABA[0])
    dlon = math.radians(KAABA[1] - lon)
    y = math.sin(dlon)
    x = math.cos(lat1) * math.tan(lat2) - math.sin(lat1) * math.cos(dlon)
    return _fix(math.degrees(math.atan2(y, x)), 360)


def compass_point(bearing):
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return points[int((bearing % 360) / 22.5 + 0.5) % 16]


# ---------------------------------------------------------------------------
# Hijri date (tabular / "Kuwaiti" arithmetic calendar)
# ---------------------------------------------------------------------------
# The arithmetic calendar can differ by a day from the moon-sighting date
# announced in your country, so the app offers a -2..+2 day adjustment.

HIJRI_MONTHS = [
    "Muharram", "Safar", "Rabi al-Awwal", "Rabi al-Thani", "Jumada al-Ula",
    "Jumada al-Akhirah", "Rajab", "Sha'ban", "Ramadan", "Shawwal",
    "Dhu al-Qadah", "Dhu al-Hijjah",
]
HIJRI_MONTHS_AR = [
    "مُحَرَّم", "صَفَر", "رَبِيع الأَوَّل", "رَبِيع الآخِر", "جُمَادَى الأُولَى", "جُمَادَى الآخِرَة",
    "رَجَب", "شَعْبَان", "رَمَضَان", "شَوَّال", "ذُو القَعْدَة", "ذُو الحِجَّة",
]
_ISLAMIC_EPOCH = 1948439.5  # 1 Muharram 1 AH (civil epoch, 16 July 622 Julian)


def _jd_from_date(date):
    return julian_day(date.year, date.month, date.day)


def hijri_to_jd(year, month, day):
    return (day + math.ceil(29.5 * (month - 1)) + (year - 1) * 354
            + math.floor((3 + 11 * year) / 30) + _ISLAMIC_EPOCH - 1)


def hijri_date(date, adjust_days=0):
    """(year, month, day) Hijri for a Gregorian date, shifted by adjust_days."""
    jd = math.floor(_jd_from_date(date) + adjust_days) + 0.5
    year = math.floor((30 * (jd - _ISLAMIC_EPOCH) + 10646) / 10631)
    month = min(12, math.ceil((jd - (29 + hijri_to_jd(year, 1, 1))) / 29.5) + 1)
    day = int(jd - hijri_to_jd(year, month, 1) + 1)
    return int(year), int(month), day


def hijri_text(date, adjust_days=0):
    y, m, d = hijri_date(date, adjust_days)
    return "%d %s %d AH" % (d, HIJRI_MONTHS[m - 1], y)
