import datetime
import os
import time

import requests
from flask import Flask, request, jsonify, abort
from werkzeug.exceptions import HTTPException
from werkzeug.routing import FloatConverter

app = Flask(__name__)

domain_root = os.environ['DOMAIN_ROOT']
ibm_root = os.environ['IBM_API_ROOT']

# For some reason, the standard float converter rejects negative numbers
# (and also integers without a decimal point).
class SignedFloatConverter(FloatConverter):
    regex = r'-?\d+(\.\d+)?'


app.url_map.converters['float'] = SignedFloatConverter


def format_date(date):
    return date.strftime("%Y-%m-%dT%H:%M:%S")


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
    user_req = requests.get(f"http://auth.{domain_root}/api/v1/me",
                            headers={'Authorization': f"Bearer {request.args['access_token']}"})
    user_req.raise_for_status()
    if not user_req.json()['is_subscribed']:
        raise HTTPPaymentRequired()

    units = request.args.get('units', 'h')
    language = request.args.get('language', 'en-US')

    forecast_req = requests.get(f"{ibm_root}/geocode/{latitude}/{longitude}/forecast/daily/7day.json?language={language}&units={units}")
    forecast_req.raise_for_status()
    forecast = forecast_req.json()

    current_req = requests.get(f"{ibm_root}/geocode/{latitude}/{longitude}/observations.json?language={language}&units={units}")
    current_req.raise_for_status()
    current = current_req.json()
    observation = current['observation']

    old_style_conditions = {
        'metadata': current['metadata'],
        'observation': {
            'class': observation['class'],
            'expire_time_gmt': observation['expire_time_gmt'],
            'obs_time': observation['valid_time_gmt'],
            # 'obs_time_local': we don't know.
            'wdir': observation['wdir'],
            'icon_code': observation['wx_icon'],
            'icon_extd': observation['icon_extd'],
            # sunrise: we don't know these, but we could yank them out of the forecast for today.
            # sunset
            'day_ind': observation['day_ind'],
            'uv_index': observation['uv_index'],
            # uv_warning: I don't even know what this is. Apparently numeric.
            # wxman: ???
            'obs_qualifier_code': observation['qualifier'],
            'ptend_code': observation['pressure_tend'],
            'dow': datetime.datetime.utcfromtimestamp(observation['valid_time_gmt']).strftime('%A'),
            'wdir_cardinal': observation['wdir_cardinal'],  # sometimes this is "CALM", don't know if that's okay
            'uv_desc': observation['uv_desc'],
            # I'm just guessing at how the three phrases map.
            'phrase_12char': observation['blunt_phrase'] or observation['wx_phrase'],
            'phrase_22char': observation['terse_phrase'] or observation['wx_phrase'],
            'phrase_32char': observation['wx_phrase'],
            'ptend_desc': observation['pressure_desc'],
            # sky_cover: we don't seem to get a description of this?
            'clds': observation['clds'],
            'obs_qualifier_severity': observation['qualifier_svrty'],
            # vocal_key: we don't get one of these
            {'e': 'imperial', 'm': 'metric', 'h': 'uk_hybrid'}[units]: {
                'wspd': observation['wspd'],
                'gust': observation['gust'],
                'vis': observation['vis'],
                # mslp: don't know what this is but it doesn't map to anything
                'altimeter': observation['pressure'],
                'temp': observation['temp'],
                'dewpt': observation['dewPt'],
                'rh': observation['rh'],
                'wc': observation['wc'],
                'hi': observation['heat_index'],
                'feels_like': observation['feels_like'],
                # temp_change_24hour, temp_max_24hour, temp_min_24hour, pchange: don't get any of these
                # {snow,precip}_{{1,6,24}hour,mtd,season,{2,3,7}day}: don't get these either
                # ceiling, obs_qualifier_{100,50,32}char: or these.
                # these are all now in their own request that you can pay extra to retrieve.
            },
        }
    }

    return jsonify(
        fcstdaily7={
            'errors': False,
            'data': forecast,
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
