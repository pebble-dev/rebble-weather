import datetime
import os
import time

import beeline
from beeline.middleware.flask import HoneyMiddleware
from beeline.patch import requests

import requests
from flask import Flask, request, jsonify, abort
from werkzeug.exceptions import HTTPException
from werkzeug.routing import FloatConverter

app = Flask(__name__)
if os.environ.get('HONEYCOMB_KEY'):
     beeline.init(writekey=os.environ['HONEYCOMB_KEY'], dataset='rws', service_name='weather')
     HoneyMiddleware(app, db_events = True)

auth_internal = os.environ['REBBLE_AUTH_URL_INT']
ibm_root = os.environ.get('IBM_API_ROOT', 'https://api.weather.com')
ibm_key = os.environ['IBM_API_KEY']
http_protocol = os.environ.get('HTTP_PROTOCOL', 'https')

# For some reason, the standard float converter rejects negative numbers
# (and also integers without a decimal point).
class SignedFloatConverter(FloatConverter):
    regex = r'-?\d+(\.\d+)?'


app.url_map.converters['float'] = SignedFloatConverter


def format_date(date):
    return date.strftime("%Y-%m-%dT%H:%M:%S")

def day_night_for_lang(day_night, language):
    # It's not clear that the Weather Channel API *ever* did this, at least,
    # as long as Rebble has been involved.  But yet, the Android app seems
    # to care about this, according to a decompilation.
    if day_night == 'D' and language[0:2] == 'de':
        return 'T'
    return day_night

def mangle_daypart(language, units, day, daypart):
    return {
        'fcst_valid': day['validTimeUtc'], # THIS IS NOT QUITE CORRECT
        'fcst_valid_local': day['validTimeLocal'],
        'day_ind': day_night_for_lang(daypart['dayOrNight'], language),
        'thunder_enum': daypart['thunderIndex'], # probably?
        'daypart_name': daypart['daypartName'], # "Tonight"
        'long_daypart_name': daypart['daypartName'], # THIS IS NOT QUITE CORRECT: should be "Thursday night"
        'alt_daypart_name': daypart['daypartName'], # "Tonight"
        # 'num' is an enumerator, not used by app
        'thunder_enum_phrase': daypart['thunderCategory'],
        'temp': daypart['temperature'],
        'hi': daypart['temperatureHeatIndex'],
        'wc': daypart['temperatureWindChill'],
        'pop': daypart['precipChance'], # XXX: is this correct?
        'icon_extd': daypart['iconCodeExtend'],
        'icon_code': daypart['iconCode'],
        # 'wxman' not used by app
        'phrase_12char': daypart['wxPhraseShort'],
        'phrase_22char': daypart['wxPhraseLong'],
        'phrase_32char': daypart['wxPhraseLong'],
        # 'subphrase_pt1' not used by app
        # 'subphrase_pt2' not used by app
        # 'subphrase_pt3' not used by app
        'precip_type': daypart['precipType'],
        'rh': daypart['relativeHumidity'],
        'wspd': daypart['windSpeed'],
        'wdir': daypart['windDirection'],
        'wdir_cardinal': daypart['windDirectionCardinal'],
        'clds': daypart['cloudCover'],
        # 'pop_phrase' not used by app
        'temp_phrase': f"{'High' if daypart['dayOrNight'] == 'D' else 'Low'} {daypart['temperature']}{'F' if units == 'e' else 'C'}.", # XXX: i18n
        # 'accumulation_phrase' not used by app
        'wind_phrase': daypart['windPhrase'],
        'shortcast': daypart['wxPhraseLong'],
        'narrative': daypart['narrative'],
        'qpf': daypart['qpf'],
        'snow_qpf': daypart['qpfSnow'],
        'snow_range': daypart['snowRange'],
        # 'snow_phrase' not used by app
        # 'snow_code' not used by app
        # 'vocal_key' not used by app
        'qualifier_code': daypart['qualifierCode'],
        'qualifier': daypart['qualifierPhrase'],
        'uv_index_raw': daypart['uvIndex'], # THIS IS NOT QUITE CORRECT, 9.7 vs 10
        'uv_index': daypart['uvIndex'],
        # 'uv_warning' not used by app
        'uv_desc': daypart['uvDescription'],
        # 'golf_index' not used by app
        # 'golf_category' not used by app
        'golf_category': 'boring sports'
    }

def new_ibm_to_old_ibm(language, units, forecast):
    # Invert the bizarre IBM dictionary-of-arrays.
    forecast_inv = []
    for k in forecast:
        if k == 'daypart':
            continue

        for day, v in enumerate(forecast[k]):
            if day >= len(forecast_inv):
                forecast_inv.append({})
            forecast_inv[day][k] = v

    # The day parts are even more brain damaged.  Invert them, too.
    if len(forecast['daypart']) != 1:
        raise ValueError(f"forecast['daypart'] had wrong number of values {len(forecast['daypart'])}")

    for k in forecast['daypart'][0]:
        for halfday, v in enumerate(forecast['daypart'][0][k]):
            # v == None?
            day = halfday // 2
            dn = "day" if ((halfday % 2) == 0) else "night"
            shouldbe = "D" if ((halfday % 2) == 0) else "N"
            if k == "dayOrNight" and v != shouldbe and v != None:
                raise ValueError(f"halfday {halfday} should be {dn}, but dayOrNight is {v}")
            if day >= len(forecast_inv):
                # There is no day to append this daypart to.
                continue
            if forecast_inv[day].get(dn) is None and v == None:
                continue
            forecast_inv[day][dn] = forecast_inv[day].get(dn, {})
            forecast_inv[day][dn][k] = v

    return [{
        'class': 'fod_long_range_daily',
        'expire_time_gmt': day['expirationTimeUtc'],
        'fcst_valid': day['validTimeUtc'],
        'fcst_valid_local': day['validTimeLocal'],
        # 'num' is an enumerator, not used by app
        'max_temp': day['temperatureMax'],
        'min_temp': day['temperatureMin'],
        # 'torcon' not used by app
        # 'stormcon' not used by app
        # 'blurb' not used by app
        # 'blurb_author' not used by app
        'lunar_phase_day': day['moonPhaseDay'],
        'dow': day['dayOfWeek'],
        'lunar_phase': day['moonPhase'],
        'lunar_phase_code': day['moonPhaseCode'],
        'sunrise': day['sunriseTimeLocal'],
        'sunset': day['sunsetTimeLocal'],
        'moonrise': day['moonriseTimeLocal'],
        'moonset': day['moonsetTimeLocal'],
        # qualifier_code is a property of a daypart now, not used by app
        # qualifier is a property of a daypart now, not used by app
        'qpf': day['qpf'],
        'snow_qpf': day['qpfSnow'],
        # snow_range is a property of a daypart now, not used by app
        # snow_phrase not used by app
        # snow_code not used by app
        **({'day':   mangle_daypart(language, units, day, day['day'])} if day.get('day') else {}),
        **({'night': mangle_daypart(language, units, day, day['night'])} if day.get('night') else {}),
    } for day in forecast_inv]


class HTTPPaymentRequired(HTTPException):
    def __init__(self, description=None, response=None):
        self.code = 402
        super().__init__(description, response)


@app.route('/heartbeat')
def heartbeat():
    return jsonify({'alive': True})

@app.route('/api/v1/geocode/<float:latitude>/<float:longitude>/')
def geocode(latitude, longitude):
    if not request.args.get('access_token'):
        abort(401)
    user_req = requests.get(f"{auth_internal}/api/v1/me",
                            headers={'Authorization': f"Bearer {request.args['access_token']}"})
    if user_req.status_code == 401:
        abort(401)
    user_req.raise_for_status()
    if not user_req.json()['is_subscribed']:
        raise HTTPPaymentRequired()
    beeline.add_context_field("user", user_req.json()['uid'])

    units = request.args.get('units', 'h')
    language = request.args.get('language', 'en-US')
    
    beeline.add_context_field("weather.language", language)
    beeline.add_context_field("weather.units", units)
    beeline.add_context_field("weather.api_version", "v2")

    forecast_req = requests.get(f"{ibm_root}/v3/wx/forecast/daily/15day?geocode={latitude},{longitude}&format=json&units={units}&language={language}&apiKey={ibm_key}")
    forecast_req.raise_for_status()
    forecast = forecast_req.json()

    old_style_fcstdaily7 = { 'forecasts': new_ibm_to_old_ibm(language, units, forecast) }

    current_req = requests.get(f"{ibm_root}/v3/wx/observations/current?geocode={latitude},{longitude}&language={language}&units={units}&format=json&apiKey={ibm_key}")
    current_req.raise_for_status()
    current = current_req.json()

    old_style_conditions = {
        'metadata': {
            'language': language,
            'transaction_id': 'lol!',
            'version': '1',
            'latitude': latitude,
            'longitude': longitude,
            'units': units,
            'expire_time_gmt': current['expirationTimeUtc'],
            'status_code': 200,
        },
        'observation': {
            'class': 'observation',
            'expire_time_gmt': current['expirationTimeUtc'],
            'obs_time': current['validTimeUtc'],
            # 'obs_time_local': we don't know.
            'wdir': current['windDirection'],
            'icon_code': current['iconCode'],
            'icon_extd': current['iconCodeExtend'],
            # sunrise: we don't know these, but we could yank them out of the forecast for today.
            # sunset
            'day_ind': current['dayOrNight'],
            'uv_index': current['uvIndex'],
            # uv_warning: I don't even know what this is. Apparently numeric.
            # wxman: ???
            'obs_qualifier_code': current['obsQualifierCode'],
            'ptend_code': current['pressureTendencyCode'],
            'dow': current['dayOfWeek'],
            'wdir_cardinal': current['windDirectionCardinal'],  # sometimes this is "CALM", don't know if that's okay
            'uv_desc': current['uvDescription'],
            # I'm just guessing at how the three phrases map.
            'phrase_12char': current['wxPhraseShort'],
            'phrase_22char': current['wxPhraseMedium'],
            'phrase_32char': current['wxPhraseLong'],
            'ptend_desc': current['pressureTendencyTrend'],
            # sky_cover: we don't seem to get a description of this?
            'clds': current['cloudCoverPhrase'], # old was 'CLR', new is 'Partly Cloudy'
            'obs_qualifier_severity': current['obsQualifierSeverity'],
            # vocal_key: we don't get one of these
            {'e': 'imperial', 'm': 'metric', 'h': 'uk_hybrid'}[units]: {
                'wspd': current['windSpeed'],
                'gust': current['windGust'],
                'vis': current['visibility'],
                'mslp': current['pressureMeanSeaLevel'],
                'altimeter': current['pressureAltimeter'],
                'temp': current['temperature'],
                'dewpt': current['temperatureDewPoint'],
                'rh': current['relativeHumidity'],
                'wc': current['temperatureWindChill'],
                'hi': current['temperatureHeatIndex'],
                'feels_like': current['temperatureFeelsLike'],
                'temp_change_24hour': current['temperatureChange24Hour'],
                'temp_max_24hour': current['temperatureMax24Hour'],
                'temp_min_24hour': current['temperatureMin24Hour'],
                'pchange': current['pressureChange'],
                'snow_1hour': current['snow1Hour'],
                'snow_6hour': current['snow6Hour'],
                'snow_24hour': current['snow24Hour'],
                'precip_1hour': current['precip1Hour'],
                'precip_6hour': current['precip6Hour'],
                'precip_24hour': current['precip24Hour'],
                # {snow,precip}_{mtd,season,{2,3,7}day}: don't get these either
                'ceiling': current['cloudCeiling'],
                # obs_qualifier_{100,50,32}char: or these.
                # these are all now in their own request that you can pay extra to retrieve.
            },
        }
    }

    return jsonify(
        fcstdaily7={
            'errors': False,
            'data': old_style_fcstdaily7,
        },
        conditions={
            'errors': False,
            'data': old_style_conditions,
        },
        metadata={
            'version': 2,
            'transaction_id': str(int(time.time())),
        },
    )
