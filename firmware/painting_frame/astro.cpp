#include "astro.h"
#include <math.h>

static const double D2R = M_PI / 180.0;

static double norm360(double d) {
  d = fmod(d, 360.0);
  return d < 0 ? d + 360.0 : d;
}

static void sun_ecliptic(double jd, double &lam, double &eps) {
  double n = jd - 2451545.0;
  double L = norm360(280.460 + 0.9856474 * n);
  double g = norm360(357.528 + 0.9856003 * n) * D2R;
  lam = norm360(L + 1.915 * sin(g) + 0.020 * sin(2 * g));
  eps = 23.439 - 0.0000004 * n;
}

static void moon_ecliptic(double jd, double &lam, double &beta, double &par) {
  double T = (jd - 2451545.0) / 36525.0;
  auto s = [T](double a, double b) { return sin(norm360(a + b * T) * D2R); };
  auto c = [T](double a, double b) { return cos(norm360(a + b * T) * D2R); };
  lam = norm360(218.32 + 481267.881 * T
                + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
                + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74)
                - 0.19 * s(357.5, 35999.05) - 0.11 * s(186.5, 966404.03));
  beta = 5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89)
         - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21);
  par = 0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.38)
        + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.70);
}

static double altitude(double lam, double beta, double eps, double jd, double lat, double lon) {
  double l = lam * D2R, b = beta * D2R, e = eps * D2R;
  double ra = atan2(sin(l) * cos(e) - tan(b) * sin(e), cos(l));
  double dec = asin(sin(b) * cos(e) + cos(b) * sin(e) * sin(l));
  double gmst = norm360(280.46061837 + 360.98564736629 * (jd - 2451545.0));
  double ha = (gmst + lon) * D2R - ra;
  double phi = lat * D2R;
  return asin(sin(phi) * sin(dec) + cos(phi) * cos(dec) * cos(ha)) / D2R;
}

SkyState sky_at(double unix_seconds, double lat, double lon) {
  double jd = unix_seconds / 86400.0 + 2440587.5;
  double sun_lam, eps, moon_lam, moon_beta, par;
  sun_ecliptic(jd, sun_lam, eps);
  moon_ecliptic(jd, moon_lam, moon_beta, par);

  SkyState s;
  s.sun_alt = altitude(sun_lam, 0.0, eps, jd, lat, lon);
  double geo = altitude(moon_lam, moon_beta, eps, jd, lat, lon);
  s.moon_alt = geo - par * cos(geo * D2R);
  s.moon_up = s.moon_alt > 0;

  double elong = acos(cos(moon_beta * D2R) * cos((moon_lam - sun_lam) * D2R));
  s.moon_illum = (1 - cos(elong)) / 2;
  s.moon_waxing = norm360(moon_lam - sun_lam) < 180.0;
  double k = s.moon_illum;
  if (k < 0.03) s.moon_phase = "new";
  else if (k > 0.97) s.moon_phase = "full";
  else if (k >= 0.40 && k <= 0.60) s.moon_phase = s.moon_waxing ? "first_quarter" : "last_quarter";
  else if (k < 0.40) s.moon_phase = s.moon_waxing ? "waxing_crescent" : "waning_crescent";
  else s.moon_phase = s.moon_waxing ? "waxing_gibbous" : "waning_gibbous";
  return s;
}
