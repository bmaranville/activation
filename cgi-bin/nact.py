#!/usr/bin/env python3
# - *- coding: utf- 8 - *-

# Using "except Except" to forward exception traceback to the user, so disable
# the pylint warnings claiming the exception is too broad.
# pylint: disable=broad-except

from __future__ import print_function

import sys
import re
import json
from math import exp
import traceback
from datetime import datetime, timedelta
from calendar import monthrange
from dataclasses import dataclass
from html import escape
from typing import Literal, Optional

from pytz import timezone, utc

import periodictable
from periodictable import elements, activation, \
        neutron_scattering, xray_sld, nsf, util, xsf
from periodictable.formulas import formula


ISO8601_RELAXED = re.compile(r"""^ # anchor to start of string
  (?P<year>[0-9]{4})               # year   YYYY
  (-(?P<month>[0-9]{1,2})          # month  -M or -MM
    (-(?P<day>[0-9]{1,2})          # day    -D or -DD
      (.                           # separator (usually T or space)
        (?P<hour>[0-9]{1,2})       # hour   H or HH
        :(?P<minute>[0-9]{2})      # minute :MM
        (:(?P<second>[0-9]{2})     # second :SS
          (\.(?P<fraction>[0-9]+)  # fractional second .SSS to arbitrary precision
          )?                       # .SSS is optional
        )?                         # SS.SSS is optional
        (?P<timezone>
          Z                        # use Z for UTC
          |
          (?P<tzprefix>[+-])       # +/- offset
          (?P<tzhour>[0-9]{1,2})   # hour offset H or HH
          (:?                      # optional separator for minute offset
            (?P<tzminute>[0-9]{2}) # minute offset MM
          )?                       # optional minute offset
        )?                         # optional time zone
      )?                           # optional time+time zone
    )?                             # YYYY-MM only
  )?                               # YYYY only
  $                                # anchor to end of the string
  """, re.VERBOSE)

# Default to the time zone is that for the NCNR.
default_timezone = timezone('US/Eastern')

#DEBUG = True
DEBUG = False

#import nsf_sears


# Crystal structures:
#
# cubic:         a = b = c and alpha = beta = gamma = 90.0 degrees.
# tetragonal:    a = b and alpha = beta = gamma = 90.0 degrees.
# orthorhombic:  alpha = beta = gamma = 90.0 degrees.
# monoclinic:    alpha = gamma = 90.0 degrees.
# triclinic:     no restrictions on a, b, c, alpha, beta or gamma.
# hexagonal:     a = b,  alpha = beta = 90.0 degrees and gamma = 120.0
# rhombohedral:  a = b = c ; alpha=beta=gamma<120  (trigonal)
# octahedral:    a = b = c, alpha = beta = gamma = 109.4712206344907
# RHDO (Rhombic Dodecahedron):
#                a = b = c, alpha = gamma = 60.0 and beta = 90.0
#
# Density:
#   a:value  => cubic
#   a:value c:value => tetragonal
#   a:value b:value c:value => orthorhombic
#   a:value b:value c:value beta:value => monoclinic
#   a:value b:value c:value alpha:value beta:value gamma:value => triclinic
#   a:value c:value gamma:value => hexagonal
#   a:value alpha:value => rhomboherdral (triagonal)
#   a:value alpha:acos(-1/3) => octahedral
#
#   a:value => a=b=c=value
#   alpha:value => alpha=beta=gamma=value
#   beta:value => alpha=gamma=90
#

def parse_density(value_str) -> tuple[Literal['default', 'volume', 'isotope', 'natural'], float]:
    if value_str == '':
        return 'default', 0
    if value_str.endswith('A3'):
        return 'volume', float(value_str[:-2])*1e-24
    if value_str.endswith('i'):
        return 'isotope', float(value_str[:-1])
    if value_str.endswith('n'):
        return 'natural', float(value_str[:-1])
    try:
        value = float(value_str)
        return ('isotope', value) if value > 0 else ('default', 0)
    except ValueError:
        pass

    # Be generous, and allow a: a= or just a, and commas or semicolons
    # between parts. This will allow poor grammar such as "a,1 : c,2"
    parts = re.split(" *[,;=: ] *", value_str.strip())
    #print >>sys.stderr,parts
    key = [_lattice_key_sub(v) for v in parts[::2]]
    try:
        val = [float(v) for v in parts[1::2]]
    except ValueError:
        raise ValueError("Expected key value pairs for lattice consants")
    if len(key) != len(val):
        raise ValueError("Expected key value pairs for lattice consants")
    if any(k not in set(('a', 'b', 'c', 'b/a', 'c/a', 'alpha', 'beta', 'gamma'))
           for k in key):
        raise ValueError("Lattice contants are a, b or b/a, c or c/a, alpha, beta, gamma")
    kw = dict(zip(key, val))

    if 'b/a' in kw:
        if 'a' not in kw:
            raise ValueError("Lattice constant b/a requires a value for a")
        kw['b'] = kw['b/a']*kw['a']
        del kw['b/a']
    if 'c/a' in kw:
        if 'a' not in kw:
            raise ValueError("Lattice constant c/a requires a value for a")
        kw['c'] = kw['c/a']*kw['a']
        del kw['c/a']
    if 'alpha' in kw:
        if 'beta' not in kw:
            kw['beta'] = kw['alpha']
        if 'gamma' not in kw:
            kw['gamma'] = kw['alpha']
    #print >>sys.stderr,kw
    return 'volume', util.cell_volume(**kw)*1e-24

def _lattice_key_sub(v):
    if v == u'α':
        return 'alpha'
    if v == u'β':
        return 'beta'
    if v == u'γ':
        return 'gamma'
    return v.lower()

def json_response(result):
    jsonstr = json.dumps(result)
    # Cross-site scripting (XSS) defense. There is no reason for the returned
    # JSON strings to include an unescaped "<" character, so if one slips
    # through from malicious inputs or from code in an error traceback it will
    # be sanitized here. Note that this is not true in general; if your web
    # service returns html strings instead of adding markup in the browser,
    # then you will need to sanitize the inputs instead of the outputs.
    jsonstr = escape(jsonstr, quote=False)
    #print(jsonstr, file=sys.stderr)
    print("Content-Type: application/json; charset=UTF-8")
    print("Access-Control-Allow-Origin: *")
    print("Content-Length: %d\n"%(len(jsonstr)+1))
    print(jsonstr)
respond = json_response

def error():
    if DEBUG:
        return traceback.format_exc()
    else:
        return str(sys.exc_info()[1])

HOUR_SCALE: dict[str, float] = {
    'h': 1,
    'm': 1./60,
    's': 1./3600,
    'd': 24,
    'w': 24*7,
    'y': 365.2425*24,
}

def parse_rest(s):
    if '-' in s or ':' in s:
        timestamp = parse_date(s.strip())
        delta = utc.localize(datetime.utcnow()) - timestamp
        hours = (delta.days*24*3600 + delta.seconds)/3600.0
        if hours < 0:
            raise ValueError("time off beam is in the future")
        return hours
    else:
        return parse_hours(s)

def parse_hours(s):
    s = s.strip()
    try:
        if s[-1] in 'hmsdwy':
            value, units = float(s[:-1]), s[-1]
        else:
            value, units = float(s), 'h'
        return value*HOUR_SCALE[units]
    except:
        raise ValueError("expected time as value and units (h,m,s,d,w,y) or beam off date/time")

def parse_date(datestring, default_timezone=default_timezone):
    """
    Parses ISO 8601 dates into datetime objects

    The timezone is parsed from the date string. However it is quite common to
    have dates without a timezone (not strictly correct). In this case the
    default timezone specified in default_timezone is used. This is UTC by
    default.

    Missing parts are assigned the latest value rather than the earliest value.
    For example, 2010-03 is returned as 2010-03-31 23:59:59.  This is done
    so that the activation estimate will be conservative.

    Raises TypeError if not passed a string.
    Raises ValueError if the string is not a valid time stamp.
    """
    #print("parse_date with",datestring)
    try:
        m = ISO8601_RELAXED.match(datestring)
    except TypeError:
        # Cruft python 2.x; in 3.x use 'raise TypeError(...) from None'
        exc = TypeError("parse_date expects a string, not %s"%(str(datestring)))
        exc.__cause__ = None
        raise exc
    if not m:
        raise ValueError("Unable to parse date string %r" % datestring)

    # For approximate dates, use latest time rather than earliest time so that
    # decay is underestimated rather than overestimated.
    groups = m.groupdict()
    year = int(groups["year"])
    month = int(groups["month"]) if groups["month"] else 12
    day = int(groups["day"]) if groups["day"] else monthrange(year, month)[1]
    hour = int(groups["hour"]) if groups["hour"] else 23
    minute = int(groups["minute"]) if groups["minute"] else 59
    second = int(groups["second"]) if groups["second"] else 59
    fraction = int(float("0.%s" % groups["fraction"]) * 1e6) if groups["fraction"] else 0
    dt = datetime(year, month, day, hour, minute, second, fraction)
    if groups["timezone"] is None:
        dt = default_timezone.normalize(default_timezone.localize(dt))
    elif groups["timezone"] == "Z":
        dt = utc.localize(dt)
    else:
        sign = +1 if groups["tzprefix"] == "+" else -1
        delta_minutes = (int(groups["tzhour"])*60
                         + (int(groups["tzminute"]) if groups["tzminute"] else 0))
        offset = sign*delta_minutes*60
        dt = utc.localize(dt) - timedelta(0, offset)
    return dt


@dataclass
class ValidatedRequest:
    """Validated and parsed request data for activation calculations."""
    calculate: Literal['scattering', 'activation', 'all']
    sample: str
    chem: 'periodictable.formulas.Formula'
    fluence: float
    fast_ratio: float
    Cd_ratio: float
    exposure: float
    mass: float
    density_type: str
    density_value: float
    rest_times: tuple[float, ...]
    decay_level: float
    thickness: float
    wavelength: float
    xray_wavelength: float
    abundance: 'periodictable.activation.ActivationTable'
    
    @classmethod
    def validate(cls, req: dict) -> tuple[Optional['ValidatedRequest'], dict]:
        """
        Validate and parse form data.
        
        Args:
            req: dict containing raw form field values
        
        Returns:
            tuple: (ValidatedRequest instance if valid else None, errors dict)
        """
        #print(req, file=sys.stderr)
        #print >>sys.stderr, "sample",req.get('sample')
        #print >>sys.stderr, "mass",req.get('mass')

        # Parse inputs
        errors = {}
        validated = {}
        
        validated['calculate'] = req.get('calculate', 'all')
        if validated['calculate'] not in ('scattering', 'activation', 'all'):
            errors['calculate'] = "calculate should be one of 'scattering', 'activation' or 'all'"
        
        try:
            validated['sample'] = req.get('sample')
            validated['chem'] = formula(validated['sample'])
        except Exception:
            errors['sample'] = error()
        try:
            validated['fluence'] = float(req.get('flux', '100000'))
        except Exception:
            errors['flux'] = error()
        try:
            validated['fast_ratio'] = float(req.get('fast', '0'))
        except Exception:
            errors['fast'] = error()
        try:
            validated['Cd_ratio'] = float(req.get('Cd', '0'))
        except Exception:
            errors['Cd'] = error()
        try:
            validated['exposure'] = parse_hours(req.get('exposure', '1'))
        except Exception:
            errors['exposure'] = error()
        try:
            mass_str = req.get('mass', '0')
            if mass_str.endswith('kg'):
                validated['mass'] = 1000*float(mass_str[:-2])
            elif mass_str.endswith('mg'):
                validated['mass'] = 0.001*float(mass_str[:-2])
            elif mass_str.endswith('ug'):
                validated['mass'] = 1e-6*float(mass_str[:-2])
            elif mass_str.endswith('g'):
                validated['mass'] = float(mass_str[:-1])
            else:
                validated['mass'] = float(mass_str)
        except Exception:
            errors['mass'] = error()
        try:
            validated['density_type'], validated['density_value'] = parse_density(req.get('density', '0'))
        except Exception:
            errors['density'] = error()
        try:
            #print >>sys.stderr,req.get('rest', [])
            rest_times = [parse_rest(v) for v in req.get('rest', [])]
            if not rest_times:
                rest_times = [0, 1, 24, 360]
            validated['rest_times'] = tuple(rest_times)
        except Exception:
            errors['rest'] = error()
        try:
            validated['decay_level'] = float(req.get('decay', '0.001'))
        except Exception:
            errors['decay'] = error()
        try:
            validated['thickness'] = float(req.get('thickness', '1'))
        except Exception:
            errors['thickness'] = error()
        try:
            wavelength_str = req.get('wavelength', '1').strip()
            if wavelength_str.endswith('meV'):
                validated['wavelength'] = nsf.neutron_wavelength(float(wavelength_str[:-3]))
            elif wavelength_str.endswith('m/s'):
                validated['wavelength'] = nsf.neutron_wavelength_from_velocity(float(wavelength_str[:-3]))
            elif wavelength_str.endswith('Ang'):
                validated['wavelength'] = float(wavelength_str[:-3])
            else:
                validated['wavelength'] = float(wavelength_str)
            #print >>sys.stderr,wavelength_str
        except Exception:
            errors['wavelength'] = error()
        try:
            xray_source = req.get('xray', 'Cu Ka').strip()
            if xray_source.endswith('Ka'):
                validated['xray_wavelength'] = elements.symbol(xray_source[:-2].strip()).K_alpha
            elif xray_source.endswith('keV'):
                validated['xray_wavelength'] = xsf.xray_wavelength(float(xray_source[:-3]))
            elif xray_source.endswith('Ang'):
                validated['xray_wavelength'] = float(xray_source[:-3])
            elif xray_source[0].isalpha():
                validated['xray_wavelength'] = elements.symbol(xray_source).K_alpha
            else:
                validated['xray_wavelength'] = float(xray_source)
            #print >>sys.stderr,"xray",xray_source,validated['xray_wavelength']
        except Exception:
            errors['xray'] = error()
        try:
            abundance_source = req.get('abundance', 'IAEA')
            if abundance_source == "IUPAC":
                validated['abundance'] = activation.table_abundance
            # CRUFT: periodictable no longer uses NIST 2001 data for abundance
            elif abundance_source == "NIST":
                validated['abundance'] = activation.table_abundance
            elif abundance_source == "IAEA":
                validated['abundance'] = activation.IAEA1987_isotopic_abundance
            else:
                raise ValueError("abundance should be IUPAC or IAEA")
        except Exception:
            errors['abundance'] = error()

        if errors:
            return None, errors
        
        return cls(**validated), {}


def extract_form_data(form: 'cgi.FieldStorage') -> dict:
    """
    Extract data from cgi.FieldStorage into a plain dict.
    
    Args:
        form: cgi.FieldStorage object
    
    Returns:
        dict with form field values
    """
    return {
        'calculate': form.getfirst('calculate', 'all'),
        'sample': form.getfirst('sample'),
        'flux': form.getfirst('flux', '100000'),
        'fast': form.getfirst('fast', '0'),
        'Cd': form.getfirst('Cd', '0'),
        'exposure': form.getfirst('exposure', '1'),
        'mass': form.getfirst('mass', '0'),
        'density': form.getfirst('density', '0'),
        'rest': form.getlist('rest[]'),
        'decay': form.getfirst('decay', '0.001'),
        'thickness': form.getfirst('thickness', '1'),
        'wavelength': form.getfirst('wavelength', '1'),
        'xray': form.getfirst('xray', 'Cu Ka'),
        'abundance': form.getfirst('abundance', 'IAEA'),
    }


def calculate(validated: ValidatedRequest):
    """
    Perform activation and scattering calculations.
    
    Args:
        validated: ValidatedRequest instance with validated parameters
    
    Returns:
        dict with calculation results
    """
    # Extract validated parameters
    calculate = validated.calculate
    sample = validated.sample
    chem = validated.chem
    fluence = validated.fluence
    fast_ratio = validated.fast_ratio
    Cd_ratio = validated.Cd_ratio
    exposure = validated.exposure
    mass = validated.mass
    density_type = validated.density_type
    density_value = validated.density_value
    rest_times = validated.rest_times
    decay_level = validated.decay_level
    thickness = validated.thickness
    wavelength = validated.wavelength
    xray_wavelength = validated.xray_wavelength
    abundance = validated.abundance

    # Fill in defaults
    #print >>sys.stderr,density_type,density_value,chem.density
    if density_type == 'default' or density_value == 0:
        # default to a density of 1
        if chem.density is None:
            chem.density = 1
    elif density_type == 'volume':
        chem.density = chem.molecular_mass/density_value
    elif density_type == 'natural':
        # if density is given, assume it is for natural abundance
        chem.natural_density = density_value
    elif density_type == 'isotope':
        chem.density = density_value
    else:
        raise ValueError("unknown density type %r"%density_type)

    if mass == 0:
        if hasattr(chem, 'total_mass'):
            mass = chem.total_mass
        elif hasattr(chem, 'total_volume'):
            mass = chem.density * chem.total_volume
        elif hasattr(chem, 'thickness'):
            mass = chem.density * chem.thickness*100.  # per cm^2
        else:
            mass = 1.

    result = {
        'success': True,
        'version': periodictable.__version__,
        }
    result['sample'] = {
        'name': sample,
        'formula': str(chem),
        # Use latex output with "$_{count}" rather than html "<sub>count</sub>"
        # because html translates "<" to "&lt;" and then to "&amp;lt". Instead
        # use sample.formula_latex.replace(/\$_{([^}]*)}\$/g, '<sub>$1</sub>')
        # to render subscripts in the web interface.
        'formula_latex': periodictable.formulas.pretty(chem, 'latex'),
        'mass': mass,
        'density': chem.density,
        'thickness': thickness,
        'natural_density': chem.natural_density,
        }

    # Run calculations
    if calculate in ('activation', 'all'):
        try:
            env = activation.ActivationEnvironment(fluence=fluence,
                                                   fast_ratio=fast_ratio,
                                                   Cd_ratio=Cd_ratio)
            sample = activation.Sample(chem, mass=mass)
            sample.calculate_activation(env,
                                        exposure=exposure,
                                        rest_times=rest_times,
                                        abundance=abundance)
            decay_time = sample.decay_time(decay_level)
            total = [0]*len(sample.rest_times)
            rows = []
            for el, activity_el in sample.activity.items():
                total = [t+a for t, a in zip(total, activity_el)]
                rows.append({
                    'isotope': el.isotope, 'reaction': el.reaction,
                    'product': el.daughter, 'halflife': el.Thalf_str,
                    'comments': el.comments, 'levels': activity_el,
                    })
            result['activation'] = {
                'flux': fluence,
                'fast': fast_ratio,
                'Cd': Cd_ratio,
                'exposure': exposure,
                'rest': rest_times,
                'activity': rows,
                'total': total,
                'decay_level': decay_level,
                'decay_time': decay_time,
            }
        except Exception:
            result['activation'] = {"error": error()}

    #nsf_sears.replace_neutron_data()
    if calculate in ('scattering', 'all'):
        try:
            sld, xs, penetration = neutron_scattering(chem, wavelength=wavelength)
            # CRUFT: periodictable < 1.5.3 does not define D2O_match
            if hasattr(nsf, 'D2O_match'):
                D2O_fraction, D2O_sld = nsf.D2O_match(chem)
            else:
                D2O_fraction, D2O_sld = None, None
            result['scattering'] = {
                'neutron': {
                    'wavelength': wavelength,
                    'energy': nsf.neutron_energy(wavelength),
                    'velocity': nsf.VELOCITY_FACTOR/wavelength,
                },
                'xs': {'coh': xs[0], 'abs': xs[1], 'incoh': xs[2]},
                'sld': {'real': sld[0], 'imag': sld[1], 'incoh': sld[2]},
                'penetration': penetration,
                'transmission': 100*exp(-thickness/penetration),
                'contrast_match': {
                    'D2O_fraction': D2O_fraction,
                    'sld': D2O_sld,
                },
            }
        except Exception:
            missing = [str(el) for el in chem.atoms if not el.neutron.has_sld()]
            if any(missing):
                msg = "missing neutron cross sections for "+", ".join(missing)
            else:
                msg = error()
            result['scattering'] = {'error': msg}


        try:
            xsld = xray_sld(chem, wavelength=xray_wavelength)
            result['xray_scattering'] = {
                'xray': {
                    'wavelength': xray_wavelength,
                    'energy': xsf.xray_energy(xray_wavelength),
                },
                'sld': {'real': xsld[0], 'imag': xsld[1]},
            }
        except Exception:
            result['xray_scattering'] = {'error': error()}
    #print("result", result, file=sys.stderr)

    return result


def api_call(request_data):
    """
    Main entry point for API request processing.
    
    Args:
        request_data: dict containing raw form field values
    
    Returns:
        dict with calculation results or error details
    """
    validated, errors = ValidatedRequest.validate(request_data)
    
    if validated is not None:
        return calculate(validated)
    else:
        return {'success': False, 'error': 'invalid request', 'detail': errors}


if __name__ == "__main__":
    import cgi
    try:
        form = cgi.FieldStorage()
        request_data = extract_form_data(form)
        response = api_call(request_data)
    except Exception:
        response = {
            'success': False,
            'version': periodictable.__version__,
            'detail': {'query': error()},
            'error': 'unexpected exception',
        }
    respond(response)
