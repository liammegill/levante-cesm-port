# SourceMods

The five files here are Gettelman et al. (2021)'s contrail-cirrus scheme,
originally from their paper's Zenodo record, with the following fixes on
top of the original (see CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md for full
detail on each):

- `aircraft_emit.F90` — ac_factor path fixed (§7 of the integration log),
  a Fortran line-length fix, the missing `cam_in` argument added to fix an
  interface mismatch with current CAM (§4.2), and `data_cycle_yr`
  hardcoded to 2019 instead of 0 (§12.1 — flagged there as a temporary
  fix; should become a namelist variable, see the integration log's
  still-open items).
- `tracer_data.F90` — the `date`/`datesec` fix, and the `CYCLICAL_LIST`
  validation bug fix (§12.2).
- `ssatcontrail.F90` — the 1.88 (2006→2020 traffic growth) multiplier
  removed, since the GAIA 2019 inventory is already present-day (§13).
- `physpkg.F90` — the `microp_aero_init`/`phys_init` interface-mismatch
  fixes (§4.1, §4.2).
- `horizontal_interpolate.F90` — unmodified, included for completeness
  since it's part of the same five-file set.

These are meant to be copied into a case's `SourceMods/src.cam/` directory
directly (see the integration log for the full case setup).
