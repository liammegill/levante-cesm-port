# Contrail-Cirrus SourceMods Integration Log

Note: this document was written with AI assistance.

Covers integrating the [Gettelman et al. (2021)](https://doi.org/10.5194/acp-21-9405-2021)
contrail-cirrus SourceMods into a working case, including MERRA2 nudging and
the use of a converted aircraft emission inventory. Done on the `cam6_2_022`
branch, building on the port covered by `LEVANTE_PORT_LOG.md` and
`CAM6_2_022_DELTA_LOG.md`.

---

## 1. SourceMods placement

The five files published by Gettelman et al. (2021) on
[Zenodo](https://doi.org/10.5281/zenodo.4584077) (`aircraft_emit.F90`,
`ssatcontrail.F90`, `tracer_data.F90`, `physpkg.F90`,
`horizontal_interpolate.F90`) were copied directly into the case's
`SourceMods/src.cam/` directory. CIME uses these automatically at build
time in place of the corresponding stock files, for this case only.

## 2. `ac_factor` hardcoded path and line-length fix

`aircraft_emit_init` (in `aircraft_emit.F90`) reads weekly scaling factors
from a hardcoded path on an NCAR home directory. Two fixes needed in the
SourceMods copy:

- The path, repointed to a file generated locally (§3).
- The resulting `open(...)` line came to 133 characters — one over
  free-form Fortran's 132-character limit — split using string
  continuation syntax.

## 3. Generating the `ac_factor` file: a 52-vs-53-week mismatch

`weekly_flight_fraction_2020all.nc` (from the paper's Zenodo record) has
52 weekly values. The Fortran code reads exactly 53
(`do m=1,53 read(101,*) ac_factor(m)`). Tracing `ssatcontrail.F90`'s
day-to-week-index formula for late December (`(335+day-1)/7+1` under
integer division) shows days 30–31 of December index into slot 53 —
52 weeks × 7 days is 364, one to two days short of a full year.

Fix: generate a 53rd value by duplicating week 52's value (the only
reasonable choice absent other information), write all 53 values as
plain whitespace-separated numbers. Resulting sequence (near 1.0
pre-COVID, dropping to ~0.33–0.35 during the March–April lockdown weeks,
recovering to ~0.87 by year end) matches the paper's own description of
the 2020 flight-reduction pattern.

## 4. Two interface mismatches between Gettelman et al.'s files and this CAM tag

`physpkg.F90` in SourceMods is a complete file replacement, not a patch —
it carries Gettelman et al.'s file exactly as it existed when written,
including surrounding code that wasn't touched. Where the stock (untouched)
CAM interfaces have since changed, the carried-along calls no longer
match. Both mismatches were found by diffing stock `physpkg.F90` (still
present, unmodified, in the main CAM checkout) against the SourceMods
copy. Principle applied throughout: Gettelman et al.'s files aren't
version-tracked; the stock CAM checkout is — fixes adapt the downloaded
files to current stock interfaces, never the reverse.

### 4.1 `microp_aero_init()` called with no arguments

Stock interface, `components/cam/src/physics/cam/microp_aero.F90`:
```fortran
subroutine microp_aero_init(pbuf2d)
```
Gettelman et al.'s `physpkg.F90` calls it with zero arguments
(`call microp_aero_init()`). `pbuf2d` is already a local variable in the
enclosing subroutine (`phys_init`). Fix: add the argument at the call site.

### 4.2 `phys_init` missing the `cam_in` argument entirely

The stock caller (`cam_comp.F90`, untouched) calls:
```fortran
call phys_init( phys_state, phys_tend, pbuf2d, cam_in, cam_out )
```
but Gettelman's `phys_init` signature only declares four arguments
(`phys_state, phys_tend, pbuf2d, cam_out`) — missing `cam_in`. Diffing
stock vs. SourceMods `physpkg.F90` showed the stock file has since gained
a "cam_snapshot" diagnostic capability and a "lunar_tides" module — both
unrelated to contrails, confirming Gettelman's baseline predates these
additions — and the declaration needed:
`type(cam_in_t), intent(in) :: cam_in(begchunk:endchunk)` (`cam_in_t`
already imported via an existing `use camsrfexch` line). Fix: add
`cam_in` to the signature and declaration. Gettelman's own code doesn't
reference `cam_in`, so this is a signature-matching fix only.

Both fixes confirmed by a subsequent clean rebuild succeeding
(`case.build --clean atm` between fixes, since `ssatcontrail.F90` is a
new file with no prior build history for `make` to reason about).

## 5. New case: `levante_sd_022`, Specified Dynamics compset

Separate case (not modifying `levante_port_test_022`), same sandbox/build
environment, CIME's `FSD` compset alias:
```
HIST_CAM60%SDYN_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV
```
— identical to the validated test compset except `CAM60` → `CAM60%SDYN`.

### 5.1 `%SDYN` defaults to 56 vertical levels, not the paper's 32

`config_component.xml` hardcodes the vertical level count by regex match
on the compset string:
```xml
<value compset="_CAM\d0%SDYN_CLM">-nlev 56</value>
```
This matches our compset regardless of preference, producing a runtime
crash (`hycoef_read: ERROR: file lev does not match model. lev (file,
model): 32  56`) against the chosen 32-level initial-condition file. The
paper states "the standard 32 levels (to 3 hPa)," so this default was
overridden:
```bash
./xmlchange CAM_CONFIG_OPTS="-phys cam6 -offline_dyn -nlev 32"
./case.build --clean-all
```
`-nlev` is a compile-time CAM configure option — CPP-defined dimension
parameters like `PLEV` are baked into compiled objects, so this needs a
full clean rebuild, not just a namelist change. Suggests the paper's own
case setup included an explicit `-nlev 32` override, since the plain
`%SDYN` compset here doesn't default to it.

### 5.2 Initial condition (`ncdata`)

No default `ncdata` exists for `RUN_STARTDATE=2019-01-01` (CAM's namelist
defaults only cover a fixed set of pre-built IC dates). Used a generic,
perpetual January-1st climatological IC instead (`ic_ymd="101"` in
`namelist_defaults_cam.xml`,
`atm/cam/inic/fv/cami-mam3_0000-01-01_1.9x2.5_L32_c150407.nc`), while
setting the model's calendar date (`RUN_STARTDATE`) to `2019-01-01` to
align with the MERRA2 nudging files, SST forcing, and other date-dependent
input — standard practice for nudged runs, since the atmospheric state
gets pulled into agreement with real meteorology within the nudging
relaxation timescale regardless of the starting point.

### 5.3 Nudging namelist (`nudging_nl`)

Confirmed present in this CAM tag (`grep` against `namelist_definition.xml`)
before use, since the paper's described mechanism (a 24-hour linear
relaxation, i.e. soft nudging) is a separate CAM feature from the older
"hard" Specified-Dynamics state-replacement mechanism and could plausibly
postdate this tag.
```
Nudge_Model = .true.
Nudge_Path = '/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/cam/met/nudging/MERRA2_fv09_32L/'
Nudge_File_Template = '%y/MERRA2_fv09.cam2.i.%y-%m-%d-%s.nc'
Nudge_Times_Per_Day = 8
Model_Times_Per_Day = 48
Nudge_Beg_Year = 2019
Nudge_Beg_Month = 1
Nudge_Beg_Day = 1
Nudge_End_Year = 2019
Nudge_End_Month = 1
Nudge_End_Day = 31
Nudge_Uprof = 1
Nudge_Ucoef = 0.125
Nudge_Vprof = 1
Nudge_Vcoef = 0.125
Nudge_Tprof = 0
Nudge_Tcoef = 0.0
Nudge_Qprof = 0
Nudge_Qcoef = 0.0
Nudge_PSprof = 0
Nudge_PScoef = 0.0
```
Winds only (matching the paper's primary configuration; temperature
nudging is a separate sensitivity test). `Model_Times_Per_Day = 48`
matches the paper's 1800 s (30-minute) timestep (86400/1800 = 48). The
0.125 coefficient approximates the paper's 24-hour relaxation timescale,
extrapolated from a documented reference pair (0.06 ↔ 50 h, 0.25 ↔ 12 h)
— not independently verified against CAM's own nudging-coefficient
formula; worth revisiting if results look off.

### 5.4 Aircraft-emission namelist: a path-doubling bug

First attempt used the full absolute path for the filelist entry in
`aircraft_specifier`:
```
aircraft_specifier = 'ac_H2O->/work/.../aircraft_gaia2019/aircraft_gaia2019_filelist.txt', ...
aircraft_datapath = '/work/.../aircraft_gaia2019'
```
This produced a doubled, nonsensical path at runtime
(`.../aircraft_gaia2019//work/.../aircraft_gaia2019/....txt`). Confirmed
by reading `aircraft_emit_register`'s own logic
(`incr_filename(..., filenames_list=spc_flist(...), datapath=air_datapath)`),
which prepends `aircraft_datapath` onto whatever's given for the filelist
automatically. Fix: use the bare filename in `aircraft_specifier`:
```
aircraft_specifier = 'ac_H2O->aircraft_gaia2019_filelist.txt',
                      'ac_SLANT_DIST->aircraft_gaia2019_filelist.txt'
aircraft_datapath = '/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/cam/chem/emis/aircraft_gaia2019'
```
Namelist-only fix — no rebuild, just `./preview_namelists` + resubmit.

---

## 6. Still-open blocker: LBC file doesn't cover 2019, and the substitute lacks required species

With everything above fixed, the run advanced further but failed inside
chemistry initialization (`mo_flbc.F90`, via `chem_surfvals.F90`) reading
the lower-boundary-condition (LBC) file for long-lived species (CH4, N2O,
CFCs, etc.).

First failure: the default LBC file
(`LBC_1750-2015_CMIP6_GlobAnnAvg_c180926.nc`) only covers through 2015 —
`RUN_STARTDATE=2019-01-01` is outside its time axis
(`flbc_inti: time out of bounds`). This is the SSP2-4.5 emissions-coverage
gap flagged in §12 of `LEVANTE_PORT_LOG.md`, now encountered directly.

Second failure, after substituting a longer-coverage file: the only
alternative `flbc_file` in this tag's `namelist_defaults_cam.xml` is
`LBC_1765-2100_1.9x2.5_CCMI_RCP60_za_RNOCStrend_c141002.nc` — RCP6.0, not
SSP2-4.5, used as a stand-in since it was the only option covering 2019.
This produced repeated `NetCDF: Variable not found` errors in
`mo_flbc.F90` — the file is missing chemical species this configuration
expects.

Needs investigation, not another quick substitution:
1. Identify the exact species list this compset's chemistry requires as
   LBC input.
2. Find a properly SSP2-4.5-consistent LBC file with the full species
   set (checking NCAR's archives directly, as with MERRA2/GAIA, rather
   than picking whatever `namelist_defaults_cam.xml` lists), or determine
   whether missing species can reasonably be held fixed/omitted for this
   study.

---

## 7. Updated still-open list (supersedes relevant items in §12 of `LEVANTE_PORT_LOG.md`)

1. LBC species/scenario gap (§6) — blocking a completed run, next priority.
2. Once resolved, the 5-timestep smoke test on `levante_sd_022` needs to
   run to completion and be verified.
3. The nudging coefficient (0.125) is an approximation, not verified
   against CAM's own formula for a true 24-hour timescale.
4. Only January 2019 MERRA2 data is in place; the full 2019–2020 range
   (§8 of `LEVANTE_PORT_LOG.md`) is needed for real experiment runs.
5. The three-way scenario comparison (full/COVID/zero aviation) and the
   ensemble-member setup (10/20 members per the paper) haven't started.
6. `cam_snapshot`/`lunar_tides` (§4.2) deliberately not backported — 
   unrelated to contrails, worth knowing they exist if needed later.

---

# Session 2: Resolving the SSP2-4.5 Blocker, Nudging Pivot, and Two Code Bugs

Picks up from §6/§7 (the LBC species/scenario blocker). Ends with a
working `levante_nudge_022_f09` case: SourceMods, soft nudging against
MERRA2, aircraft emissions, and SSP2-4.5 forcing, running together at f09
resolution.

## 8. A structural correction: hard vs. soft forcing, and dropping `%SDYN`

The case had been built on the `%SDYN` compset modifier (`-offline_dyn`),
the wrong tool for this study. `%SDYN` replaces CAM's own dynamical core
outright, reading meteorology directly from `metdata_nl`/`met_data_file`
— a hard mechanism with no relaxation timescale, since there's nothing to
relax when the state is overwritten every timestep.

The paper (Gettelman et al. 2020 and 2021) states a 24-hour linear
relaxation — meaningless for hard replacement, only sensible for soft
nudging (`nudging_nl`), where CAM's dynamical core runs normally and a
relaxation term is added to its own tendency, pulling toward MERRA2
rather than replacing the state. This matters here specifically because
the contrail scheme's premise is that injected aircraft water vapor
interacts with the model's own humidity/temperature/cloud fields — under
hard forcing those fields could be overwritten before the model's physics
response to the injected water vapor has a chance to matter.

Fix: dropped `%SDYN`. New case built on the plain
`HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV` compset already
validated in Section 1, with `nudging_nl` added via `user_nl_cam`. This
also means the `-nlev 56` compset default (§5.1) never applies — plain
CAM6 defaults to 32 levels, matching the paper and the chosen initial
condition.

## 9. Grid resolution: 0.9x1.25 (f09), not f19

The properly-regridded, 32-vertical-level MERRA2 nudging product (NSF
NCAR GDEX dataset d313002) is only available at 0.9x1.25 — no 1.9x2.5
option exists for this correctly-regridded dataset (only the other,
wrong dataset — d313003, 72 levels, needing its own vertical regridding
— offers multiple resolutions). Case switched to CIME's `f09_f09_mg17`
grid alias (exactly 0.9x1.25, no new nudging data needed) — also closer
to the paper's stated ~1° target resolution. Required re-fetching the
f09-resolution equivalents of every standard input file already fetched
at f19 (topo, domain, SST, initial condition, CMIP6 emissions, CLM
surface data), via the same targeted per-file `svn export` approach as
the original f19 fetch.

## 10. A stack-overflow bug, found by isolating stock CAM

Switching to f09 produced a segfault (signal 11) deep in `mo_drydep.F90`
(dry deposition velocity / land-use-fraction mapping), across most MPI
ranks simultaneously, no Fortran error message.

Isolation test: built a bare-bones, stock (no SourceMods, no nudging, no
aircraft emissions) f09 case. It crashed identically, same routine, same
MPI task number — ruling out anything in SourceMods, nudging, or namelist
additions.

Root cause: `mo_drydep.F90` uses large automatic (stack-allocated) local
arrays — `tmp_frac_lu(plon,n_land_type,plat)` and
`tmp_soilw_3d(plon,12,plat)` — sized by the model's grid dimensions. At
f09 (plon=288, plat=192) these are roughly 4x larger than at f19,
totalling ~11 MB combined — exceeding Levante's default 8 MB
(`ulimit -s` = 8192) per-process stack limit. At f19 the same arrays
total under 3 MB, within the limit, which is why this wasn't seen before
switching resolutions. A raw segfault (not a "subscript out of bounds"
message) even under `DEBUG=TRUE`/bounds-checking is a useful diagnostic
signature of stack overflow rather than an indexing bug — bounds
checking only catches language-level array violations, not running out
of stack space for a correctly-indexed array.

Fix: added a `resource_limits` block to the Levante entry in
`config_machines.xml`, setting the stack to unlimited:
```xml
<resource_limits>
  <resource name="RLIMIT_STACK">-1</resource>
</resource_limits>
```
Must go as a sibling after the closing `</environment_variables>` tag,
not nested inside it — the schema validator catches this if placed
wrong: `xmllint --noout --schema config_machines.xsd
config_machines.xml`. `case.setup` confirms the fix is live: `Setting
resource.RLIMIT_STACK to -1 from (8388608, -1)`. Confirmed by rerunning
the stock isolation case, which completed end-to-end at full (1024-task)
scale.

Added to `patches/cime.patch` on this branch. Still needs syncing to the
`cam6_2_020` branch's `cime.patch` — any future f09 (or finer) run built
from that setup would hit the same stack overflow.

## 11. The SSP2-4.5 emissions/forcing gap, resolved beyond just LBC

§6 identified the default LBC file only covers to 2015. The same gap
affects several other input-file categories, discovered one at a time
via runtime crashes.

### 11.1 Lower boundary condition (LBC) — fixed
`LBC_2014-2500_CMIP6_SSP245_0p5degLat_GlobAnnAvg_c190301.nc` (§6-7) —
carried over unchanged into this case.

### 11.2 Surface/vertical aerosol and reactive-species emissions
The default `CMIP6_emissions_1750_2015` directory's ~23
anthropogenic/biomass-burning species-sector files (SO2, DMS, bc_a4,
pom_a4, so4_a1/a2, num_a1/a2/a4, SOAGx1.5, across anthro/bb/anthro-ene/
anthro-ag-ship/anthro-res sectors) were swapped for their
`emissions_ssp245/` equivalents — confirmed by direct inspection to be
bit-identical to the historical data through 2015, concatenated with the
SSP2-4.5 projection through 2101 (verified via the SSP245 file's own
embedded processing-history attribute, naming the historical file it was
built from). Same units (`molecules/cm2/s`), same variable-naming
convention (`emiss_bb` etc.).

Two species (`num_pom_a4`, `pom_a4`) needed a substring-match fix in the
old-to-new-file mapping script: `pom_a4_anthro_surface` matched as a
substring inside `num_pom_a4_anthro_surface` (a different species). Fixed
by requiring the match to start immediately after the known SSP245
filename prefix.

### 11.3 Volcanic (`contvolcano`) and biogenic (`SOAG`) sources

- Volcanic (`contvolcano`) files: `date` variable shows coverage of year
  850 to year 5000 (`emissions-cmip6_*_contvolcano_vertical_850-5000_*.nc`
  — literal, not a typo). A deliberately sparse (84 entries across 4150
  years) long-term reference dataset for roughly-constant background
  degassing, covering 2019 as-is. Kept unchanged.
- Biogenic (`SOAGx1.5_biogenic_surface`): capped at 2015 (`date` variable
  spans 1750-01-16 to 2015-12-16, 3192 monthly entries). No SSP245-
  consistent replacement found — checked the `emissions_ssp245/`
  directory (nothing), the `CMIP6_emissions_2000climo/` directory (has a
  biogenic file, but scoped to `scam="1"`/`camiop="1"` single-column-model
  cases per its own namelist-defaults tagging; using it reproduced the
  same time-bounds crash), and CAM's dynamic MEGAN biogenic-VOC scheme
  (`megan_emis_nl`, present in this tag but not active in this chemistry
  configuration — enabling it would need a broader mechanism change).
  Decision: drop this entry from `srf_emis_specifier` as a documented
  simplification — a minor background SOA precursor source, not central
  to the aviation water-vapor question this study addresses. Worth
  checking NCAR's own published CESM2 SSP-scenario convention here before
  a final production run.

### 11.4 Stratospheric ozone, halons, and CH4-oxidation water vapor
Three more files, found via runtime crashes, same pattern (default file
capped at 2015, SSP2-4.5-consistent replacement in the same source
directory):
- `prescribed_ozone_file`/`prescribed_strataero_file` (same file for
  both): swapped `ozone_strataero_WACCM_L70_zm5day_18500101-20150103_
  CMIP6ensAvg_c180923.nc` (capped 2015-01-03) for
  `ozone_strataero_WACCM_L70_zm5day_18500101-21010201_CMIP6histEnsAvg_
  SSP245_c190403.nc` (extends to 2101-02-01).
- `tracer_cnst_file` (halons): swapped
  `tracer_cnst_halons_3D_L70_1849-2015_CMIP6ensAvg_c180927.nc` (capped
  2015-12-16) for `tracer_cnst_halons_3D_L70_1849-2101_CMIP6ensAvg_
  SSP2-4.5_c190403.nc` (extends to 2101-12-16).
- `H2OemissionCH4oxidationx2` (`ext_frc_specifier`, stratospheric water
  vapor from methane oxidation): swapped `.../elev/
  H2OemissionCH4oxidationx2_3D_L70_1849-2015_CMIP6ensAvg_c180927.nc`
  (capped 2015-12-16) for `.../elev/H2OemissionCH4oxidationx2_3D_L70_
  1849-2101_CMIP6ensAvg_SSP2-4.5_c190403.nc` (extends to 2101-12-16).

### 11.5 Lesson: the split datapath+filename convention breaks naive audits
A script-based audit of every file path in `atm_in` (53 unique full-path
entries, checked via `netCDF4` for `date`/`time` coverage against 2019)
initially missed `tracer_cnst_file`, `prescribed_ozone_file`, and
`prescribed_strataero_file` entirely, because these variables store only
a bare filename, with the directory given separately via a companion
`*_datapath` variable (the same convention `aircraft_specifier`/
`aircraft_datapath` uses) — a search for full `/work/...` paths doesn't
match these. Any future audit should also `grep -i "_datapath\s*=" atm_in`
and reconstruct full paths for bare-filename entries before checking
coverage. (`_filelist`-style entries are a third convention, used by
`aircraft_specifier` and supported by `tracer_cnst_filelist`, though
empty/unused here.)

Static/climatological files need no date-coverage check: no `time`
dimension, or a `time` dimension with no `time` coordinate variable (the
convention for a repeating 12-month climatology, e.g. `season_wes.nc`,
`clim_soilw.nc`, `regrid_vegetation.nc`), and the initial condition
(`ncdata`), read once as a starting snapshot.

## 12. Two code bugs found and fixed in `tracer_data.F90`/`aircraft_emit.F90`

With every input file covering 2019, the run advanced further but hit two
more issues inside the aircraft-emission SourceMods themselves.

### 12.1 `aircraft_emit.F90`: `data_cycle_yr` hardcoded to 0

`aircraft_emit_init` calls `trcdata_init(..., rmv_file, 0, 0, 0, air_type)`
— the first `0` is `data_cycle_yr`. Since `air_type = 'CYCLICAL_LIST'`,
this flows into `file%cyc_yr`, used by `get_model_time` to compute the
comparison time against the file's own data times (via
`set_time_float_from_date`). With `cyc_yr=0`, the comparison used "year
0" instead of the simulated year (2019), producing a negative time value
and a crash (`find_times: all(all_data_times(:) > time)`).

Fix (temporary, see §14/§17): changed the hardcoded `0` to `2019` in the
SourceMods copy, with a `TODO` comment. `aircraft_cycle_yr` should be a
namelist variable instead — see the still-open list.

### 12.2 `tracer_data.F90`: `CYCLICAL_LIST` incorrectly rejected by validation

Setting `data_cycle_yr` hit a second problem: a validation check
```fortran
if ( (.not.file%cyclical) .and. (data_cycle_yr>0._r8) ) then
   call endrun('trcdata_init: Cannot specify data_cycle_yr if data type is not CYCLICAL')
endif
```
only exempts `'CYCLICAL'` type, rejecting `'CYCLICAL_LIST'`. But the
code's own usage of `cyc_yr`, a few lines further down, is guarded by
`if (file%cyclical .or. file%cyclical_list)` — treating both types
identically. The validation was never extended to match. This is stock
CAM code (untouched by Gettelman's edits, just carried along in the
full-file replacement).

Fix: extended the check to exempt `cyclical_list` too:
```fortran
if ( (.not.file%cyclical) .and. (.not.file%cyclical_list) .and. (data_cycle_yr>0._r8) ) then
   call endrun('trcdata_init: Cannot specify data_cycle_yr if data type is not CYCLICAL or CYCLICAL_LIST')
endif
```

With both fixes, `levante_nudge_022_f09` completed a 5-timestep run
cleanly (`case.run` + `case.st_archive`, both `COMPLETED` exit `0:0`,
full restart set at `2019-01-01-09000`) — the first complete run of the
integrated setup (SourceMods + soft nudging + aircraft emissions +
SSP2-4.5 forcing, at f09).

## 13. The 1.88 traffic-growth multiplier removed from `ssatcontrail.F90`

Flagged as an open issue in the original port log but not acted on until
now: `ssatcontrail.F90` applied a hardcoded `*1.88_r8` factor to both
`ac_H2O` and `ac_SLANT_DIST`, Gettelman's own 2006-to-2020 air-traffic
growth assumption for his 2006-baseline inventory. Since the GAIA 2019
inventory already represents present-day traffic for both quantities,
this factor would double-count growth, inflating the water-vapor forcing
by 88%. Removed from both lines, retaining `curr_factor` (weekly COVID
scaling):
```fortran
ac_H2O = ac_H2O*curr_factor  ! 1.88 (2006->2020 traffic growth) removed: GAIA 2019 inventory is already present-day
ac_SLANT_DIST = ac_SLANT_DIST*curr_factor  ! 1.88 removed, same reason as ac_H2O above
```

## 14. Still-open items (supersedes the list in Section 1, §7)

1. `aircraft_cycle_yr` should be a namelist variable, not a hardcoded
   `2019` in the SourceMods source: add a namelist entry read in
   `aircraft_emit_readnl`, following the pattern already used there for
   `aircraft_datapath`/`aircraft_specifier`, stored in a module-level
   variable, passed into `trcdata_init` instead of the literal `2019`.
   Running a different simulation year currently requires editing and
   rebuilding the SourceMods copy.
2. Biogenic emissions gap (§11.3) — deliberately dropped. Check NCAR's
   own published CESM2/SSP-scenario convention before a final production
   run.
3. The f09 stack-size fix (§10) needs syncing to the `cam6_2_020`
   branch's `cime.patch`.
4. Full 2019-2020 MERRA2 transfer (only January 2019 in place at time of
   writing), the 0.125 nudging coefficient verification, the
   three-scenario ensemble setup, and the ~1e-10 K per-member temperature
   perturbation.
5. Any future change of simulation year should start with the full
   programmatic file-coverage audit (§11.5) rather than incremental
   crash-driven discovery.

---

# Session 3: A 2019 Seasonal Pattern for `ac_factor`, and a Leap-Year Bug

## 15. `ac_factor` extended to a real 2019 seasonal pattern

`ac_factor` — a 53-entry, 2020-only weekly COVID-affected flight fraction
— predates 2019 entirely. A flat `curr_factor = 1.0` baseline for 2019
would discard real seasonal structure (more traffic in northern-hemisphere
summer, less in winter): the paper's own Figure 1(c) (monthly average
flights per year, 2016-2019, plus a multi-year average) shows this
variation directly, and user-supplied OpenSky daily flight-count data for
2019 confirms it.

`ac_factor` extended from 53 to 106 entries — weeks 1-53 hold a 2019
seasonal pattern, weeks 54-106 the original 2020 COVID-affected pattern,
unchanged. The 2019 half was built from 365 days of OpenSky flight-count
data, bucketed into the same sequential 7-day windows the code already
uses (day 1-7 = week 1, ..., final 53rd bucket holding day 365 alone —
matching the 2020 array's own irregular tail), each week's average count
normalized by 2019's own overall daily average (values fluctuate around
1.0, matching the 2020 array's convention). Result: dips to ~0.78-0.84 in
Jan-Feb, rises to ~1.05-1.15 across Jun-Sep peak summer travel, tapers
back toward ~1.0 by year-end, no discontinuity at the year boundary (week
53 ends at 0.986, week 54 begins at 0.977). Saved as
`data/ac_factor_2019_2020.dat` in this repository.

## 16. Calendar-convention bugs in the week-index calculation (two, found across two sessions)

`ssatcontrail.F90`'s original per-month day-offset chain
(`ac_factor((335+day-1)/7+1)` for December, etc.) used offsets (31, 60,
91, 121, 152, 182, 213, 244, 274, 305, 335) only internally consistent
for a leap year: the jump from January's implicit offset (31) to March's
(60) requires February to have contributed 29 days. True for 2020 (the
year this code was written for) but not 2019 or any other non-leap year
— every date from March onward would misalign by one day if these
offsets were reused for a second, non-leap year.

First fix: replaced the hardcoded per-month chain with CAM's
`get_curr_calday()` (`time_manager.F90`), returning day-of-year via
ESMF's calendar-aware calculation:
```fortran
calday = get_curr_calday()
week_idx = int((calday - 1.0_r8) / 7.0_r8) + 1
if( yr.eq.2020 ) week_idx = week_idx + 53
curr_factor = ac_factor(week_idx)
```
`aircraft_emit.F90`'s `ac_factor` declaration and file-reading loop
updated to match (53 → 106 entries, filename `ac_factor_2019_2020.dat`).

**Validation exposed a second bug.** A throwaway debug case (separate
from the production case, `RUN_STARTDATE` set directly to specific test
dates, one timestep, debug prints added to `ssatcontrail.F90`) was used
to confirm the running code's actual output against hand-calculated
expected values for 2019-04-08 and 2020-04-08.

Two implementation notes from setting this up:
- `write(*,*)` (bare stdout) silently truncated output mid-line in this
  MPI environment once the line got long enough (five values on one
  line); every other write statement in this codebase uses
  `write(iulog,*)`, which did not truncate. Keep debug prints short (one
  or two values per write) and use `iulog`, not `*`.
- `get_curr_calday()`'s result print showed `98.0` for 2020-04-08, not
  the expected ordinal day-of-year 99. This is not a bug: `get_curr_calday()`
  returns elapsed days since Jan 1 00Z (0-indexed — midnight of April 8
  is 98 full days elapsed), not the 1-indexed ordinal day-of-year. The
  `-1` in `int((calday - 1.0_r8) / 7.0_r8) + 1` was double-subtracting,
  since `calday` is already effectively "day-of-year minus 1." This
  happened to cancel out correctly for 2019 (non-leap) but not 2020,
  exposing the bug only when the leap-year test was run.

Second fix — remove the extra `-1`:
```fortran
week_idx = int(calday / 7.0_r8) + 1
```
Verified against both target dates via the debug case: 2019-04-08 →
`week_idx=15`, `curr_factor=0.915248`; 2020-04-08 → `week_idx=68`
(`15+53`), `curr_factor=0.351890`. Both match independent hand
calculation. Also note: this compset uses a `NO_LEAP` calendar (every
year treated as a uniform 365 days internally, confirmed via
`./xmlquery CALENDAR`) — `get_curr_calday()` returns `98.0` for April 8
regardless of nominal year, consistent with `NO_LEAP` never inserting a
leap day.

Rebuilt and resubmitted with both fixes: `case.run` + `case.st_archive`
both `COMPLETED` exit `0:0`, full restart set at `2019-01-01-09000`.

## 17. Updated still-open items

- Item 2 from Session 2's §14 (whether `ac_factor` needs 2019 handling)
  resolved by §15-16.
- Item 1 from Session 2's §14 (`aircraft_cycle_yr` should be a namelist
  variable) still applies, and now also covers `curr_factor`'s year check
  (`if (yr.eq.2020)`), itself hardcoded to the years this study covers —
  a future run covering different years needs both this and
  `data_cycle_yr` updated together, ideally via the same namelist-driven
  mechanism.
- Everything else in Session 2's §14 remains open.

---

# Session 4: Longer Test Runs, History Output, and a Namelist-Architecture Note

## 18. Restart mechanism and wall-clock scaling, confirmed via a 2-day test

Extended the production case (`levante_nudge_022_f09`) from the 5-timestep
smoke test to `STOP_OPTION=ndays`/`STOP_N=2`, `REST_OPTION=ndays`/
`REST_N=1` (daily restarts). Completed in 4:27 — faster than the original
5-timestep test (5:05), confirming most of that earlier time was fixed
startup overhead (reading input files, building the nudging file list for
the first time), not per-timestep cost. Restart files at
`2019-01-02-00000` and `2019-01-03-00000` confirm `REST_N=1` working
correctly — this was the first test to exercise a MERRA2 nudging-file
day-boundary transition and an actual restart write/continue cycle.

Full 2019 and 2020 MERRA2 data (fetched separately via Globus) verified:
file naming matches the `Nudge_Path`/`Nudge_File_Template` convention
exactly, per-year subdirectories present, file counts exactly correct
(2019: 2920 = 365 days × 8/day; 2020: 2928 = 366 days × 8/day, correctly
reflecting the leap year). `Nudge_End_Year`/`Month`/`Day` updated in
`user_nl_cam` to `2020`/`12`/`31` to cover the full range.

## 19. History output: no dedicated contrail diagnostic exists

Checked `ssatcontrail.F90` and `physpkg.F90` for any `outfld`/`addfld`/
`pbuf_add_field` call related to contrails — none exist. The scheme adds
water vapor and ice directly into CAM's existing humidity/cloud fields
with no separate named diagnostic; the contrail signal only exists as the
difference between scenarios in ordinary state fields, matching the
paper's own full-air/no-air/COVID differencing methodology.

Set `nhtfrq = -24`, `mfilt = 10` (daily-averaged history, `h0` stream) for
testing — production runs should match the paper's own monthly
comparison (CAM's default `nhtfrq`, no override needed) once the setup is
otherwise finalized.

Checked the resulting `h0` file's variable list against the paper's
Figure 2/3 quantities:

| Paper quantity | CAM field(s) |
|---|---|
| SW/LW cloud radiative effect | derived from `FSNT`/`FSNTC` and `FLNT`/`FLNTC` |
| Net TOA radiation | derived from `FSNT` − `FLNT` |
| Ice water path | `TGCLDIWP` |
| High cloud fraction | `CLDHGH` |
| Cloud-top ice effective radius | `AREI` |
| Cloud-top ice number concentration | likely `NUMICE` or `AWNC` — not yet distinguished |
| Land surface temperature | uncertain — CAM's `TS` mixes land/ocean/ice; a land-specific CLM field is likely needed. CLM history output not yet configured with a matching frequency override, so unchecked. |

## 20. Namelist architecture for hardcoded physics parameters (discussion, no code changed)

Several values are hardcoded in the SourceMods that a user might
reasonably want to change without editing and rebuilding source:
`ssatcontrail.F90` has `eta = 0.3_r8` (propulsion efficiency, Ponater
2002) and `Q = 43.e6` (specific combustion heat, Schumann 1996) as local
variables assigned inline in the subroutine that uses them; the
`ac_factor` file path is hardcoded in `aircraft_emit.F90` (§2). Separately,
`EI_H2O` (water vapor emission index, 1.237) is not in the Fortran code
at all — it's a parameter in the standalone GAIA-to-CAM conversion
script, already exposed there as a `--ei-h2o` CLI flag, applied before
the data ever reaches CAM.

For values inside the Fortran code, CESM's standard mechanism (already
working for `aircraft_datapath`/`aircraft_specifier`) has four layers:

1. A module-level variable with a default, declared once at the top of
   the module (matching `air_type = 'CYCLICAL_LIST'`, already present in
   `aircraft_emit.F90`). `eta` and `Q` would need lifting from local to
   module scope.
2. A namelist-read subroutine — `aircraft_emit.F90` already has one
   (`aircraft_emit_readnl`): defines a local `namelist` block, reads the
   relevant section of `atm_in`, broadcasts to all MPI tasks, assigns
   into the module-level variables. New variables would extend this same
   subroutine's namelist block (or a new group, if they belong logically
   to `ssatcontrail` rather than `aircraft_emit_nl`).
3. `namelist_definition.xml` (`components/cam/bld/namelist_files/`) —
   registers the variable's name, type, namelist group, and description
   with CIME's `build-namelist`; without an entry here nothing in
   `user_nl_cam` referencing it reaches `atm_in`.
4. `namelist_defaults_cam.xml` — optional fallback value used when the
   user doesn't override it in `user_nl_cam`.

Following this pattern, `ac_factor`'s file path would become e.g. an
`aircraft_factor_file` namelist variable, structurally identical to
`aircraft_datapath`. `EI_H2O` has two options: leave it in the conversion
script (already configurable, no CAM-side change needed), or move the
calculation into CAM itself (input file would carry raw fuel-burn rate
instead of pre-computed water-vapor mass, `aircraft_emit.F90` would
multiply by an `EI_H2O` namelist variable at runtime — a larger change,
since it moves where the water-vapor calculation happens).

This bundles naturally with the `aircraft_cycle_yr` item already in the
still-open list (§14/§17) — all namelist-architecture follow-up work for
`aircraft_emit_nl`, not separate one-offs.

## 21. Updated still-open items

- Items from §17 remain open.
- Land surface temperature output source (CAM `TS` vs. a CLM field) —
  unresolved, see §19.
- Cloud-top ice number concentration variable name — `NUMICE` vs. `AWNC`
  not yet distinguished, see §19.
- Namelist-architecture change for `eta`, `Q`, the `ac_factor` path, and
  (optionally) `EI_H2O` — discussed in §20, not implemented.
- Two properly-configured (not throwaway) test cases for an April 2019
  vs. April 2020 comparison — planned, not yet built.

---

# Session 5: Ensemble Setup, Scaling, and a January Sanity Check

## 22. Figure 2's baseline: three ensembles, five differences, no non-nudged case

Confirmed from the paper's own text (§2.3), not inferred. Three ensembles:
**full air** (2020-equivalent traffic, no COVID), **no air** (zero aviation
water vapor), **COVID** (actual 2020 traffic, restarted from full air on
1 January 2020). Every Figure 2 line is one ensemble mean minus another:
`full air − no air` (orange: 2020 met; green: 2019 met) isolates aviation's
effect; `COVID − full air` (blue) isolates COVID specifically. Solid lines
= wind-only nudging (the paper's primary method). Dashed lines
(red/purple) = wind+temperature nudging, run as **only two** additional
ensembles ("full air T nudge", "COVID T nudge") — a sensitivity test, not
a second full set. No line in Figure 2 uses zero nudging.

For this project's goal (matching Figures 3-6, both `full air − no air`
comparisons using the paper's standard wind-only nudging): only the
three-ensemble, wind-only setup is needed. No temperature-nudged runs
required.

## 23. Ensemble mechanism: `NINST` + `pertlim`, both confirmed working

CIME's multi-instance capability (`NINST_<COMPONENT>`) and CAM's
`pertlim` namelist variable (`cam_initfiles_nl`, "Perturb the initial
conditions for temperature randomly by up to the given amount") together
implement the paper's 10-member, small-temperature-perturbation ensemble
— no custom code needed.

Setting `NINST_ATM=NINST_LND=NINST_ICE=NINST_OCN=NINST_ROF=10` (all
prognostic components must match) and running `case.setup` auto-creates
per-instance namelist files (`user_nl_cam_0001` ... `_0010`, one per
component), each starting as a copy of the existing shared `user_nl_cam`
— nothing already configured is lost. `pertlim` is CAM-specific; no
equivalent exists (or is needed) for CLM/CICE/DOCN/MOSART, since a single
perturbed atmospheric initial state cascades into divergent land/ice/
river states as the coupled system evolves.

**`pertlim`'s random seed is deterministic, not instance-specific**
(`dynamics/fv/dyn_comp.F90`: `rndm_seed = i + (j-1)*nglon`, based purely
on global column index). Identical `pertlim` across all 10 instances
would produce bit-for-bit identical runs — zero ensemble spread. Fix:
give each instance a distinct `pertlim` value (`1.01e-10` ... `1.10e-10`
used here), all on the same order of magnitude as the paper's stated
~1e-10 K. The random *pattern* is shared across instances; only the
*scale* differs — sufficient to seed genuinely diverging trajectories
once the model's chaotic dynamics run forward, confirmed directly:
restart-file `T` differed between instance 1 and instance 10 by up to
4.8 K after 5 timesteps (mean diff ~0.008 K; large max/small mean is the
expected signature of localized chaotic growth, not a red flag).

The deterministic, grid-location-only seeding is deliberate, not an
oversight: it keeps runs exactly reproducible regardless of task count
(needed for debugging, automated testing, and cross-run comparison) and
independent of MPI decomposition (seed depends on global column index,
not local/rank-based indexing, so results don't change with how the
domain is split across tasks).

## 24. Namelist config is read fresh at every job start, restart or not

A CESM restart starts a **new executable process** for every job
submission. Only prognostic model state (T, Q, winds, surface fields —
what the restart file actually stores) carries over; everything
namelist-driven (nudging settings, aircraft emissions config, `ac_factor`)
is re-read from that job's own `atm_in` every time, since `phys_init`
(and `aircraft_emit_init` within it) runs from scratch on every
submission. Practical consequence: switching `ac_factor` files (or any
other namelist setting) at a restart boundary works correctly without
needing the namelist-configurable-path refactor discussed previously —
it just requires a rebuild (different hardcoded path) at that point
rather than a `user_nl_cam` edit. Refactor deferred: `physpkg.F90` (and
likely the rest of the SourceMods) will need re-diffing against stock
CAM again for any future CESM/CAM version port anyway (as already
happened once, `cam6_2_020`→`cam6_2_022`), making a refactor now low
value relative to redoing it properly as part of that future work.

## 25. Three-case design: full air, COVID, no air

- **full air** (non-COVID): new `ac_factor_full_air.dat` — the 2019
  seasonal pattern (§15) duplicated into both halves of the 106-entry
  array, representing the best available proxy for "2020 traffic absent
  COVID" (no genuine non-COVID 2020 data exists). Confirmed length still
  correct despite 2020 being a leap year: `week_idx = int(calday/7)+1`
  caps at 53 for both 365-day (2019) and 366-day (2020) years under this
  formula — the extra leap day just makes week 53 span two calendar days
  instead of one, the same class of tail-end approximation as the
  original week-53 padding decision (§3).
- **COVID**: existing `ac_factor_2019_2020.dat`, unchanged. Identical to
  full air for all of 2019 by construction (both files' first 53 entries
  are the same 2019 data) — diverges only once the simulation reaches
  2020. Per §24, can be restarted from the full-air run at 1 January
  2020 (matching the paper's own approach, §22) via a rebuild pointing at
  this file instead of `ac_factor_full_air.dat`.
- **no air**: `aircraft_specifier = ''`. Confirmed via direct code read
  (`aircraft_emit.F90`): `if (air_specifier(1) == "") return` sets
  `aircraft_cnt=0` and returns immediately, before the `ac_factor` file
  read is ever reached — the SourceMods themselves don't need modifying
  or removing for this case, only the namelist entry. Removing the
  SourceMods entirely (considered, then rejected) would have reintroduced
  the `microp_aero_init`/`cam_in` interface fixes (§4), unrelated to
  aircraft emissions.

## 26. DKRZ partition specifications (confirmed authoritative, from DKRZ's own docs)

| Partition | Max nodes/job | Max runtime | Shared node use |
|---|---|---|---|
| `compute` | 512 | 8h | no |
| `shared` | 1 | 7 days | yes |
| `interactive` | 1 | 12h | yes |
| `gpu` | 60 | 12h | yes |
| `gpu-devel` | 1 | 30min | yes |

The `shared` partition allows at most one node per job (for
small/serial/single-node jobs). `compute`'s real node cap is 512, correcting
this repo's own `config_batch.xml` placeholder (`nodemax="500"`,
originally flagged as unconfirmed) — worth fixing in that file, not yet
done.

## 27. Node-count scaling test: real speedup, real cost, zero effect on results

Same 1-month, 10-instance "no air" workload, run at two node counts on
`compute`:

| Nodes | Tasks | Wall-clock (1 month) | Node-hours |
|---|---|---|---|
| 4 | 512 | 2:13:22 | ~8.9 |
| 16 | 2048 | 0:44:56 | ~12.0 |

~3x wall-clock speedup for 4x the nodes (~74% parallel efficiency); ~35%
*more* total node-hours for the faster option — a genuine tradeoff
(speed vs. compute budget), not a free win in both directions. Consistent
across two independent 4-node runs ("full air" partial timeout data and
"no air" completed run both gave ~2h/month).

**Results confirmed decomposition-independent, not just theoretically but
directly tested**: `T` field from the 4-node and 16-node runs, same
instance, same day (`2019-01-31` daily-mean), bit-for-bit identical
(max/mean abs diff = 0.0). Node count is a pure performance/cost choice
here with zero risk of affecting output.

## 28. January sanity check against the paper's Figure 2

Computed from the completed January "full air"/"no air" 10-member
ensembles (`full air − no air`, 2019 meteorology — the paper's green
line). Ensemble-mean, area-weighted global means:

- **Net TOA radiation** (`FSNT − FLNT`): difference = **0.378 W/m²**.
  Confirmed against the actual paper figure (not just the abstract's
  annual-mean ERF, ~62 mW/m², which is a different quantity/period): the
  paper's own Figure 2 January value is ~0.4 W/m² — close agreement.
- **Ice water path** (`TGCLDIWP`): difference = 0.263 g/m². Not
  comparable to the paper's Figure 2(c) as computed — that panel's units
  (g/kg) indicate a cloud-top ice **mixing ratio**, not a column-
  integrated path (kg/m² vs. g/kg are different physical quantities, not
  interchangeable via a unit conversion). Likely candidate found:
  `ICIMR` ("prognostic in-cloud ice mixing ratio", kg/kg, full 3D field
  `time,lev,lat,lon`) — needs per-column extraction at the actual
  cloud-top level (not a fixed level index), analogous to how `AREI`/
  `NUMICE` (also already in the default `h0` output) are presumably
  defined. Not yet implemented — deferred to a full pass covering all of
  Figure 2/3's variables together, once more months of data exist.
- **Land surface temperature**: CAM's `TS` is mixed land/ocean/ice: used
  CLM's own `TSKIN` ("skin temperature") instead, land-area-weighted
  (`landfrac` × cos(lat), CLM's monthly `h0` file). Difference =
  **0.0065 K** — consistent with the paper's own statement that this
  quantity takes ~4-5 months to stabilize; near-zero this early is
  expected, not a null result.

Both statistically-robust (differences well above ensemble spread — e.g.
net TOA: 0.378 W/m² diff vs. ~0.03-0.055 W/m² ensemble std) and physically
sensible in sign and rough magnitude. Good indication the full pipeline
(nudging, GAIA emissions, contrail SourceMods, ensemble mechanism) is
producing a real, correctly-signed aviation effect at approximately the
right scale, one month in.

## 29. Continuing to 4 months total

Both "full air" and "no air" cases resumed from their 1 February 2019
restart (`CONTINUE_RUN=TRUE`, `STOP_N=3` — relative to the restart point,
not the original start date) for 3 further months, at 4 nodes.
`JOB_WALLCLOCK_TIME` raised from 4h to 7:30 (3 months × ~2.2h/month ≈
6.6h estimated; original 4h caused the "full air" 6-month attempt to
`TIMEOUT` rather than complete). Both jobs confirmed starting from the
correct date (`2019-02-01`) via the same log-grep method used throughout
this project.

## 30. Updated still-open items

- `ICIMR`/`AREI`/`NUMICE` cloud-top extraction (per-column, not fixed
  level index) — needed for a proper Figure 2(c)-(e) comparison, deferred
  to a full multi-variable pass (§28).
- `config_batch.xml`'s `nodemax="500"` for `compute` should be corrected
  to `512` (§26) — not yet done.
- Everything in Session 4's §21 not superseded above remains open
  (namelist architecture for `eta`/`Q`/`ac_factor` path, still deferred
  per §24's reasoning above).
