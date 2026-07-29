#!/usr/bin/env python3
"""
convert_aviation_emissions_to_cam.py

Convert a sparse (index-based) aviation emission inventory -- one row per
populated (lat, lon, plev) grid cell, as produced by flattening a regular
3D grid -- into the gridded NetCDF format required by CESM's
aircraft_emit.F90 / tracer_data.F90 (the Gettelman et al. 2021 aviation
water-vapor contrail-cirrus scheme).

Produces two forcing fields on a regular (lon, lat, lev) grid:
  - ac_H2O         [kg/kg/sec]  water-vapor mass-mixing-ratio tendency
  - ac_SLANT_DIST  [m/sec]      flight-distance accumulation rate

Background on why the two fields need different treatment, and why the
file needs the metadata it does, is in CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md
and LEVANTE_PORT_LOG.md in this repository. Summary:

  - ac_H2O must be pre-divided by this file's own grid-cell air mass,
    because CAM's vertical remapping for this field (vert_interp_mixrat,
    confirmed by reading tracer_data.F90 directly) treats the input as
    an already-mixing-ratio quantity and only converts mass -> mixing
    ratio at the *target* (model) grid, using the *source* file's own
    implied layer air mass (via hyai/hybi) to reconstruct the source
    layer boundaries. Supplying an absolute mass here would be silently
    wrong once remapped.
  - ac_SLANT_DIST is NOT mass-normalized -- its remapping routine
    (vert_rebin) has the mass->mixing-ratio step disabled, so it must
    stay in native units (m/s), not divided by air mass.
  - PS/hyam/hybm/hyai/hybi are mandatory even for genuinely fixed
    pressure levels, because CAM's conserve_column remapping
    (hardcoded on for aircraft data) unconditionally reconstructs layer
    boundaries from them. Fixed pressure levels are represented within
    this required hybrid-coordinate format by setting hybm=hybi=0.
  - `date` (integer, YYYYMMDD) is a mandatory variable in the time
    dimension -- CAM's cyclical-file logic reads it directly
    (year = date/10000) to match simulation year to data year. `datesec`
    is optional and defaults to 0 if absent.

Usage:
    python3 convert_aviation_emissions_to_cam.py \\
        --input emi_inv_gaia_2019.nc \\
        --output aircraft_emissions_gaia2019_cam.nc \\
        --year 2019

If the input file already has an 'H2O' variable (mass, kg, annual total),
pass --h2o-var to use it directly instead of deriving from fuel:
        --h2o-var H2O
Otherwise H2O is derived from a fuel-burn variable (--fuel-var, default
'fuel', in kg) using a water-vapor emission index (--ei-h2o, default
1.237 kg H2O per kg fuel).
"""

import argparse
import calendar

import numpy as np
import netCDF4 as nc


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True,
                   help="Source sparse inventory NetCDF file")
    p.add_argument("--output", required=True,
                   help="Output CAM-compatible gridded NetCDF file")
    p.add_argument("--year", type=int, required=True,
                   help="Calendar year the inventory totals represent "
                        "(used for the 'date' variable and to correctly "
                        "handle leap-year seconds-per-year)")

    p.add_argument("--lat-var", default="lat", help="Latitude variable name (default: lat)")
    p.add_argument("--lon-var", default="lon", help="Longitude variable name (default: lon)")
    p.add_argument("--plev-var", default="plev", help="Pressure-level variable name, hPa (default: plev)")
    p.add_argument("--distance-var", default="distance",
                   help="Flight-distance variable name, km, annual total (default: distance)")

    p.add_argument("--h2o-var", default=None,
                   help="H2O mass variable name (kg, annual total), if already present in the "
                        "input file. If not given, H2O is derived from --fuel-var * --ei-h2o.")
    p.add_argument("--fuel-var", default="fuel",
                   help="Fuel-burn variable name, kg, annual total (default: fuel)")
    p.add_argument("--ei-h2o", type=float, default=1.237,
                   help="Water-vapor emission index, kg H2O per kg fuel burned "
                        "(default: 1.237)")

    p.add_argument("--earth-radius", type=float, default=6.371e6, help="meters (default: 6.371e6)")
    p.add_argument("--gravity", type=float, default=9.80665, help="m/s^2 (default: 9.80665)")
    p.add_argument("--p0", type=float, default=100000.0,
                   help="Reference pressure for hybrid coefficients, Pa (default: 100000, CAM's own default)")

    return p.parse_args()


def seconds_per_year(year):
    return (366 if calendar.isleap(year) else 365) * 24 * 60 * 60


def infer_grid_spacing(vals):
    """Median spacing between sorted unique coordinate values -- robust to
    a missing cell or two at the grid edges, unlike checking only the first
    gap."""
    diffs = np.diff(vals)
    return float(np.median(diffs))


def main():
    args = parse_args()

    src = nc.Dataset(args.input)
    lat_pts = src.variables[args.lat_var][:]
    lon_pts = src.variables[args.lon_var][:]
    plev_pts = src.variables[args.plev_var][:]  # hPa
    dist_pts = src.variables[args.distance_var][:]  # km, annual total

    if args.h2o_var is not None:
        h2o_pts = src.variables[args.h2o_var][:]  # kg, annual total
        print(f"Using H2O directly from variable '{args.h2o_var}'")
    else:
        fuel_pts = src.variables[args.fuel_var][:]  # kg, annual total
        h2o_pts = fuel_pts * args.ei_h2o
        print(f"Derived H2O from '{args.fuel_var}' * EI_H2O={args.ei_h2o}")
    src.close()

    # ---- Reconstruct the regular grid ----
    # Ascending order = top-of-atmosphere first (smallest pressure), matching
    # CAM's standard vertical-level convention (index 0 = model top).
    lat_vals = np.sort(np.unique(lat_pts))
    lon_vals = np.sort(np.unique(lon_pts))
    plev_vals = np.sort(np.unique(plev_pts))

    nlat, nlon, nlev = len(lat_vals), len(lon_vals), len(plev_vals)
    print(f"Grid: {nlev} levels x {nlat} lats x {nlon} lons = {nlev * nlat * nlon} cells "
          f"({len(lat_pts)} populated)")

    lat_spacing = infer_grid_spacing(lat_vals)
    lon_spacing = infer_grid_spacing(lon_vals)
    if not np.isclose(lat_spacing, lon_spacing, rtol=0.01):
        print(f"WARNING: inferred lat spacing ({lat_spacing:.4f} deg) and lon spacing "
              f"({lon_spacing:.4f} deg) differ -- check this is really a regular grid.")
    print(f"Inferred grid spacing: {lat_spacing:.4f} deg (lat), {lon_spacing:.4f} deg (lon)")

    lat_idx = np.searchsorted(lat_vals, lat_pts)
    lon_idx = np.searchsorted(lon_vals, lon_pts)
    lev_idx = np.searchsorted(plev_vals, plev_pts)

    # Dense arrays, annual totals, zero where no flights occurred
    dist_total = np.zeros((nlev, nlat, nlon))  # km
    h2o_total = np.zeros((nlev, nlat, nlon))   # kg

    dist_total[lev_idx, lat_idx, lon_idx] = dist_pts
    h2o_total[lev_idx, lat_idx, lon_idx] = h2o_pts

    # ---- Grid-cell air mass (to convert H2O mass -> mixing-ratio tendency) ----
    # Layer interfaces: midpoint (in pressure) between adjacent level centers,
    # with the top and bottom interfaces extrapolated symmetrically.
    lev_interfaces = np.zeros(nlev + 1)
    lev_interfaces[1:-1] = 0.5 * (plev_vals[:-1] + plev_vals[1:])
    lev_interfaces[0] = plev_vals[0] - (lev_interfaces[1] - plev_vals[0])
    lev_interfaces[-1] = plev_vals[-1] + (plev_vals[-1] - lev_interfaces[-2])
    dp = np.diff(lev_interfaces) * 100.0  # hPa -> Pa, shape (nlev,), positive

    lat_south = lat_vals - lat_spacing / 2.0
    lat_north = lat_vals + lat_spacing / 2.0
    cell_area_per_lat = (args.earth_radius ** 2) * np.deg2rad(lon_spacing) * (
        np.sin(np.deg2rad(lat_north)) - np.sin(np.deg2rad(lat_south))
    )  # shape (nlat,), m^2

    air_mass = (dp[:, None, None] / args.gravity) * cell_area_per_lat[None, :, None]
    air_mass = np.broadcast_to(air_mass, (nlev, nlat, nlon))

    # ---- Convert annual totals to required rate units ----
    spy = seconds_per_year(args.year)
    print(f"Seconds in {args.year}: {spy} ({'leap' if calendar.isleap(args.year) else 'non-leap'} year)")

    ac_slant_dist = (dist_total * 1000.0) / spy   # km -> m, then per second (NOT air-mass normalized)
    h2o_rate_kg_s = h2o_total / spy                # kg/s
    ac_h2o = h2o_rate_kg_s / air_mass               # kg/kg/s (air-mass normalized)

    # ---- Write output file ----
    out = nc.Dataset(args.output, "w", format="NETCDF4")
    out.createDimension("lon", nlon)
    out.createDimension("lat", nlat)
    out.createDimension("lev", nlev)
    out.createDimension("ilev", nlev + 1)
    out.createDimension("time", 1)

    v_lon = out.createVariable("lon", "f8", ("lon",))
    v_lon[:] = lon_vals
    v_lon.units = "degrees_east"

    v_lat = out.createVariable("lat", "f8", ("lat",))
    v_lat[:] = lat_vals
    v_lat.units = "degrees_north"

    v_lev = out.createVariable("lev", "f8", ("lev",))
    v_lev[:] = plev_vals  # hPa; nominal display coordinate only -- actual
    v_lev.units = "hPa"   # pressure reconstruction uses hyam/hybm/PS below
    v_lev.positive = "down"

    v_time = out.createVariable("time", "f8", ("time",))
    v_time[:] = [0.0]
    v_time.units = f"days since {args.year}-01-01 00:00:00"
    v_time.calendar = "gregorian" if calendar.isleap(args.year) else "noleap"

    # Mandatory: CAM reads 'date' (YYYYMMDD) directly to match simulation
    # year to data year for cyclical/time-varying forcing files.
    v_date = out.createVariable("date", "i4", ("time",))
    v_date[:] = [args.year * 10000 + 101]  # YYYY0101
    v_datesec = out.createVariable("datesec", "i4", ("time",))
    v_datesec[:] = [0]

    v_p0 = out.createVariable("P0", "f8")
    v_p0[:] = args.p0
    v_p0.units = "Pa"

    v_hyam = out.createVariable("hyam", "f8", ("lev",))
    v_hyam[:] = (plev_vals * 100.0) / args.p0  # hPa -> Pa, then normalize by P0
    v_hyam.long_name = "hybrid A coefficient at layer midpoints"

    v_hybm = out.createVariable("hybm", "f8", ("lev",))
    v_hybm[:] = 0.0
    v_hybm.long_name = "hybrid B coefficient at layer midpoints (zero: pure pressure levels)"

    v_hyai = out.createVariable("hyai", "f8", ("ilev",))
    v_hyai[:] = (lev_interfaces * 100.0) / args.p0
    v_hyai.long_name = "hybrid A coefficient at layer interfaces"

    v_hybi = out.createVariable("hybi", "f8", ("ilev",))
    v_hybi[:] = 0.0
    v_hybi.long_name = "hybrid B coefficient at layer interfaces (zero: pure pressure levels)"

    v_ps = out.createVariable("PS", "f8", ("time", "lat", "lon"))
    v_ps[:] = 101325.0  # arbitrary constant -- irrelevant to reconstructed pressure since hybm=hybi=0
    v_ps.units = "Pa"

    v_h2o = out.createVariable("ac_H2O", "f8", ("time", "lev", "lat", "lon"), fill_value=0.0)
    v_h2o[0, :, :, :] = ac_h2o
    v_h2o.units = "kg/kg/sec"
    v_h2o.long_name = f"Aircraft water vapor emission tendency (annual average, {args.year})"

    v_dist = out.createVariable("ac_SLANT_DIST", "f8", ("time", "lev", "lat", "lon"), fill_value=0.0)
    v_dist[0, :, :, :] = ac_slant_dist
    v_dist.units = "m/sec"
    v_dist.long_name = f"Aircraft flight distance accumulation rate (annual average, {args.year})"

    out.Title = "CESM aircraft emission forcing (aircraft_emit.F90-compatible)"
    out.Source_file = args.input
    out.Year = args.year
    if args.h2o_var is None:
        out.EI_H2O = args.ei_h2o
    out.Note = ("Annual-average static pattern; any temporal variation (e.g. weekly COVID "
                "scaling) should be applied externally, not baked into this file.")

    out.close()

    print(f"\nWrote {args.output}")
    print(f"ac_H2O range (nonzero): {ac_h2o[ac_h2o > 0].min():.3e} to {ac_h2o.max():.3e} kg/kg/s")
    print(f"ac_SLANT_DIST range (nonzero): {ac_slant_dist[ac_slant_dist > 0].min():.3e} "
          f"to {ac_slant_dist.max():.3e} m/s")

    # ---- Mass-conservation self-check ----
    recomputed_h2o_total = np.sum(ac_h2o * air_mass) * spy
    recomputed_dist_total = np.sum(ac_slant_dist) * spy / 1000.0
    orig_h2o_total = np.sum(h2o_pts)
    orig_dist_total = np.sum(dist_pts)
    print(f"\nMass-conservation check:")
    print(f"  H2O:      original total = {orig_h2o_total:.6e} kg, "
          f"recomputed = {recomputed_h2o_total:.6e} kg, "
          f"ratio = {recomputed_h2o_total / orig_h2o_total:.6f}")
    print(f"  distance: original total = {orig_dist_total:.6e} km, "
          f"recomputed = {recomputed_dist_total:.6e} km, "
          f"ratio = {recomputed_dist_total / orig_dist_total:.6f}")
    print("  (both ratios should be ~1.000000; if not, something is wrong)")


if __name__ == "__main__":
    main()
